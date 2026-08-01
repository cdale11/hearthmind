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

**`docs/README.md` is the index to every other document** (filed
v1.34.64): which one answers which question, which are still
authoritative, and which are finished history now under `docs/archive/`.
Consult it before opening a doc by filename guess.

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

**Body/Mind framing (explicit user correction, 2026-07-21, standing —
full text docs/VISION-2026-07-21-SELFEVOLVING.md's "v1.2 revision
note").** Don't describe the LLM as a layer "bolted on to" deterministic
simulation, and don't scope pillar work as "simulation + optional LLM
enhancement." Instead: each of the four pillars (Humans, Village,
Nature, Innovation) is one system with two inseparable halves — **Body**
(deterministic, always-authoritative objective reality for that pillar)
and **Mind** (LLM, that pillar's subjective cognition — perception,
memory interpretation, belief formation, goal reasoning, planning,
social/cultural interpretation, concept invention). The Mind is the
pillar's cognition, not decoration or post-processing. A pillar whose
Mind half is thin is incomplete, not "correctly mostly-deterministic by
design" — closing that gap is real future work, not scope creep (Nature
was this gap; closed v1.3.27, see "Current state" below). This doesn't
loosen the call-budget gating below (core cast, daily ceiling,
`critical` scheduling) — it's a completeness target for what deserves a
Mind, not license to remove the gating. Reflection (Phase 5, designed
not yet built) is not a fifth pillar — it's the meta-cognitive system
observing all four Minds, one level up, never touching Body state or
inventing facts directly.

**Every pillar expands the shared ontology, not just Innovation
(explicit user correction, same session).** `world/ontology.py`'s
`InventedConcept` registry is a cross-pillar capability: Humans
originate customs/professions/social roles/myths/traditions, Village
originates institutions/laws/festivals/political structures, Nature
originates ecological relationships/migration routes/habitats/climate
phenomena, Innovation originates technologies/techniques/philosophies/
theories — all into the SAME registry so any system can discover/
reference/combine/reinterpret/evolve/merge across origins indefinitely.
`ONTOLOGY_CATEGORIES` was already architected to span all four
pillars' flavors, but scheduling had collapsed to one Village-gated
mechanism (fixed v1.3.27 — see `llm/nature_mind.py`, `ontology_llm.
VILLAGE_PROPOSE_CATEGORIES`). A genuine Human-vs-Village origination
split (today both still route through the Village-imagination job)
remains open, flagged.

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

## Long-term design vision (2026-07, standing — full text in docs/archive/VISION-2026-07.md)

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
Awake) — see docs/archive/VISION-2026-07.md (now trimmed to a status pointer)
for the phase-by-phase shipping record and the two flagged conflicts'
resolutions. **All six phases (I-N) are fully shipped** (v0.76.1
through v0.84.4) — this is no longer a design-only document, it
describes the shape the engine actually has.

**`docs/archive/IDEAS-2026-07-EMERGENCE.md`** (filed v0.87.6, an externally-
submitted "what's still missing" audit, extended with original ideas
§1-§9 across later batches): **also fully resolved** as of v0.87.31 —
every checklist item across §0-§9 is either shipped, confirmed
already-shipped under another name, or (§8's LoRA fine-tuning item
only) explicitly and correctly left as data-collection-only pending a
real training-pipeline effort outside `SimulationEngine`'s scope. Kept
as a historical decision record (like docs/DECISIONS.md); work from it
again only on future explicit direction naming a specific item.

**`docs/MASTERCHECKLIST-2026-07-22.md`** (filed v1.4.7, a user-uploaded
consolidated audit covering det_sys.md's 25-item deterministic "Body"
and LLM_Pillars.md's five-pillar cognitive "Mind," plus the Body↔Mind
"Seam"): **design/planning only, nothing built from it yet** — the doc
itself carries a 4-phase thematic sequence; a companion "Implementation
roadmap" section appended at the bottom breaks that into 30 concrete,
independently-shippable steps (Stage I senses/substrate, 3 steps;
Stage II the five minds, 6 steps; Stage III player-facing/interaction,
5 steps; Stage IV deepen the Body, 16 steps — 5 checklist items are
standing review-time discipline, not separate steps). Same standing
convention as every other vision doc here: work from it only on future
explicit direction naming a specific step. The core finding worth
remembering even before any step ships: most of today's Body systems
are generated-once-at-creation and static/random-walk thereafter
(rivers carved once, a 9-region climate grid not per-tile fields, no
material/affordance/genetics/chemistry model) — det_sys.md's "procedural
generation as continuous runtime, not a world-gen step" is the
through-line gap. One design decision is explicitly flagged as needed
before Stage III's step 14 (Humans collective vs. individual-NPC
disagreement in dialogue/chronicle) — not blocking on anything earlier.

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

**The Living Map (explicit user directive, 2026-07-24 — full text
docs/VISION-2026-07-24-LIVINGMAP.md).** Standing philosophy, not a
one-shot feature: Hearthmind should never read as "a static
procedurally generated map with moving agents placed on top of it" —
it should read as a living landscape continuously rewritten by
civilization, nature, and time, where a player can reconstruct the
world's history by looking at the map alone, with every overlay
disabled if need be. Every deterministic system (hydrology, terrain
evolution, ecology, climate, civilization growth, degradation) should
have SOME real map representation, not diagnostics-only visibility —
this is a completeness bar to keep checking against on every future
batch that touches map rendering, same standing-discipline shape as
A23-A25. When a new overlay is added, it must answer one specific,
nameable gameplay question at a glance (per the vision doc's own
worked examples — fertility -> where to farm, moisture -> irrigation/
river influence) — never a raw uniform tint a player has to guess the
meaning of.

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
`tech_level` (ten-era ladder as of v0.90.0: `stone_age -> bronze_age ->
iron_age -> classical -> medieval -> renaissance -> industrial ->
electrical -> modern -> digital`, settlements now start `stone_age`),
each a real unlock (FORGE past stone_age, LIBRARY past iron_age,
FACTORY/POWER_PLANT past industrial, AUTOMOBILE past modern); carts/
mounts stay foundable at every era. World genesis (v0.89.0): a preview
terrain is generated from real entropy before the one-time genesis LLM
call (when `--seed` is omitted; explicit `--seed` skips it, resumed
worlds never re-run it), so the founding scenario is grounded in what's
actually near spawn and that same entropy becomes the final world
seed — the narrated land and the generated map are now guaranteed to
match, not just independently varied.
Settlement naming: instant deterministic placeholder inside
`World.tick()`, LLM proposes a better name in the background and
silently replaces it.

**Weather/disaster threshold lesson (standing):** `compute_weather`'s
EMA smoothing produces a much narrower realized range than the raw
jitter suggests. If a threshold-gated event "never seems to happen,"
first verify the threshold is *reachable* against measured smoothed
output (snow, sky bands, wind bands, storms, heatwave, frost were all
this bug class) — don't just raise the roll chance. **v1.34.64 added
two hard rules to this.** (a) **Measure over a full year, all twelve
months.** At 100 ticks/day a 9,000-tick probe covers ~90 days —
spring only, the driest quarter — and that sample produced two wrong
conclusions in this very pass before being caught. Drive
`compute_weather` directly with a real `SimClock` (fast, faithful)
rather than ticking a world; note `SimClock.month_name` is
capitalized while `_MONTH_BASELINES` is lowercase-keyed, a mismatch
that silently empties a per-month table instead of erroring. (b)
**When a fix changes two variables, verify each is load-bearing
separately** — v0.88.0's flood fix raised a threshold AND rebalanced
gain/decay; only the second was needed, and the first swapped a
ratchet bug for its exact inverse (an unreachable one) that then went
unnoticed for dozens of versions.

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

## The Adaptive Runtime's prime invariant (B0, filed v1.34.161)

Second architectural law, same enforcement weight as the Body/Mind
split above (docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B, "build
this first"): **gameplay systems declare *what* work exists. The
runtime decides *when*, *where*, and *how* it executes. Gameplay never
makes scheduling, threading, batching, or hardware decisions.**
Concretely: `world/`, `agents/`, `settlement/`, `economy/` may never
import `threading`/`concurrent.futures`, call `time.sleep`, or spawn an
executor — those are execution-layer concerns that belong to the tick
loop / `simulation/engine.py` and (once B1-B15 exist) the future task
scheduler, never to a subsystem describing its own domain logic.
Mechanically checked by `scripts/verify_runtime_invariant.py` (same
standalone-script convention as `verify_hearthbench_isolation.py` —
run manually, no CI pipeline exists in this repo to wire it into yet).
**Migration reality (B0.3):** today ~200 schedule points still live
directly inside `engine.py` and its subsystems (`_TICK_JOBS`,
`_schedule_llm_job`, every `_maybe_schedule_*`/`_maybe_tick_*` call) —
this law governs *new* code the same way R7 governs new physical-
substrate code; migrating the existing ~200 onto a real B1 task graph
is the bulk of Part B and, per B1.4, must happen incrementally, one
subsystem at a time, each verified against `scripts/verify_replay_
hash.py` — never a big-bang rewrite.

## Current state (v1.34.176)

Explicit user instruction: "Every AI/ML subsystem should itself
participate in Hearthmind's evolutionary architecture. It should
accumulate experience, periodically retrain from the world's history,
support variation, inheritance and adaptation where appropriate, and
become part of the simulation's long-term emergent ecosystem rather
than remaining a static optimization layer." A real gap: L5 (v1.34.172)
gives one model lineage ONTOGENY — continual learning across its own
lifetime — but nothing gave a model population real PHYLOGENY:
variation and selection across many candidate configurations. Every
model in L0-L5 was, structurally, still "the one true configuration,
retrained in place."

New `hearthmind/ml/evolution.py` (Tier 6's L6), deliberately reusing —
not reinventing — the exact evolutionary shape this codebase already
has twice over: `world/ontology.py`'s `InventedConcept` (a `lineage`
dict of `evolved_from`/`merged_from`, a bounded `fitness_history`, a
`generation` counter, fitness-gated `run_selection`) and `agents/
population.py`'s diploid genetic inheritance (draw each gene from a
randomly-chosen parent allele, small-scale mutation, never a full
reroll). `ModelGenome`: a model's own tunable hyperparameters
(learning rate, hidden width, epochs, replay fraction) as a real
heritable genome, field-for-field mirroring `InventedConcept`.
`mutate_genome` (asexual variation + inheritance, clamped so mutation
explores rather than teleports) and `crossover_genome` (sexual
variation + inheritance, uniform gene-by-gene draw from one of two
parents — rejects crossing two genomes of different species).
`GenomePopulation.evaluate_and_select`: a real (μ+λ) evolutionary
step — score every genome, keep the fittest survivors, refill the
population via mutation/crossover of survivors. `train_and_score_
genome`: the one place a genome's genes become a real trained
`primitives.MLP` (via `ml.training.train_mlp_sgd`) and get scored
(fitness = `1/(1+holdout_loss)`, bounded, NaN-safe).

Composes with what's already shipped rather than duplicating it: L5
still owns how ONE resulting model keeps learning across its own
lifetime; L5.3's `passes_shadow_gate` is reused directly as the real
safety check a genome's trained model must clear before replacing a
live champion; cross-run pooling (`cross_run.py`) still supplies the
data a genome gets scored against. Distinct from B13.5's own
evolutionary tunable search (Runtime CONTROL parameters — concurrency,
cache sizes) — L6 evolves LEARNED MODEL hyperparameters, a different
gene space, same evolutionary mechanism, no duplication.

**Not wired into any real evolutionary cadence or `simulation/
engine.py` call site** — same "never big-bang" discipline as every
Tier 5/6 module. Real future work: a genuine per-species evolutionary
cadence keyed to simulated time (same shape B9's `TimescaleGate` would
drive), and threading a `GenomePopulation`'s champion genome into L5's
own continual-retrain loop so a model's hyperparameters keep adapting
alongside its weights, not just its weights alone.

Verified: `scripts/verify_ml_evolution.py` (27 checks — every gene
stays within its legal bounds across 50 random draws and 50 repeated
large mutations; mutation records real variation plus correct parent/
generation lineage; crossover inherits each gene from one of exactly
two named parents and rejects cross-species crossover; a well-tuned
genome scores measurably higher than a badly-tuned one on the same
toy task; the load-bearing check — a genome population's mean fitness
climbs substantially and the best genome's hyperparameters genuinely
converge toward a real synthetic optimum over 15 generations; fitness
history persists across survivors) — all pass. `pyflakes` clean on
the new module (the 4 pre-existing `engine.py` findings — undefined
names `Agent`/`Building`/`Institution` — are long-documented and
unrelated to this change). `scripts/verify_runtime_invariant.py`/
`verify_task_graph.py`/`verify_scheduler.py`/`verify_dormancy.py`/
`verify_tuning.py`/`verify_hardware_profile.py`/`verify_ml_substrate.py`/
`verify_forecasting.py`/`verify_timescales.py` re-run clean
(unaffected). No native module, persisted `World` state, or real
engine code path touched — no soak re-run needed.

## Current state (v1.34.175)

Explicit user instruction: "Start B9" (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Tier 5). New `hearthmind/simulation/timescales.py`'s
`TimescaleLadder`: the doc's own tick→minute→hour→day→week→month→
season→year ladder, with every rung's minimum tick interval derived
from a world's own calendar shape (`SimClock`'s own `sim_minutes_
per_tick`/`minutes_per_day`/`days_per_month` conventions) rather than
a guessed constant — verified against hand-computed calendar math
(1440 min/day at 5 sim-min/tick = exactly 288 ticks/day) and that a
faster tick rate produces a correspondingly larger tick-count floor
for the same real calendar day. `enforce(timescale, requested_
interval)` is B9.1's real enforcement: a task's own configured
interval can never be shorter than its declared timescale's floor — a
per-tick request against a "day" timescale is clamped up, not merely
flagged.

`ElapsedTimeTracker`/`TimescaleGate` (B9.2): generalizes `Dormancy
Manager.wake()`'s own "always return the real elapsed tick count"
contract (B4.3) beyond dormancy specifically — `elapsed_since` is
non-mutating and returns `None` (not `0`) for a task with no prior
baseline, since there's genuinely no history to integrate from yet,
a different case from "zero time has passed." `TimescaleGate.check`
combines both halves into the one call a real scheduled task would
make: verified a brand-new task never fires on its first observation,
fires exactly once its declared timescale's real floor has elapsed,
and that elapsed time is measured from the last REAL firing rather
than an intervening no-op check — the property that makes "running a
slow system less often is mathematically equivalent, not an
approximation" actually true for a generic consumer. Also verified two
tasks at different declared timescales (daily vs. monthly) behave
fully independently against the same ladder.

B9.3 (a live audit of the ~200 real per-tick call sites in `engine.py`
for timescale mismatch) explicitly NOT attempted — same "needs
individual live judgment, not a mechanism" class as B3.3's own audit
deferral; this pass ships the tool such an audit would use, not the
audit itself. **Not wired into any real control point** — same
"never big-bang" discipline as every prior B-item; no import from
`timescales.py` exists in `simulation/engine.py`.

Verified: `scripts/verify_timescales.py` (26 checks — ladder
monotonicity, calendar-derived floor correctness, rank/is_slower_than,
enforce()'s clamping in both directions, the elapsed-tracker's
None-vs-baseline semantics and non-mutating peek, the gate's full
due/elapsed lifecycle including the "measured from last real firing"
property, and two independently-timescaled tasks not interfering) —
all pass. `pyflakes` clean. `scripts/verify_runtime_invariant.py`/
`verify_task_graph.py`/`verify_scheduler.py`/`verify_dormancy.py`/
`verify_tuning.py`/`verify_hardware_profile.py`/`verify_ml_substrate.py`/
`verify_forecasting.py` re-run clean (unaffected). No native module,
persisted `World` state, or real engine code path touched — no soak
re-run needed.

## Current state (v1.34.174)

Explicit user instruction: "Continue tier 5 and the AI/ML models
should learn from all previous runs if possible."

**Tier 5's B8 — Predictive scheduling, all four sub-items.** New
`hearthmind/simulation/forecasting.py`, same "never big-bang"
discipline as every prior Tier 5 Runtime module. B8.1
`WorkloadForecaster`: a small `hearthmind.ml.primitives.MLP` regressor
over `WORKLOAD_FORECAST_SCHEMA` (backlog, recent dialogue/cognition
rate, active-disaster flag, festival-scheduled flag, season) — the
item's own three named triggers (storm → dialogue/cognition spike,
harvest season → economy surge, a scheduled festival → event burst)
map directly onto this vector, so a new trigger is a schema field, not
a new pipeline. Verified: training measurably cuts loss on synthetic
data and the trained model correctly predicts higher load when
`active_disaster=1`. B8.2 `plan_reservation`: a deterministic,
capacity-bounded reservation hint (never a hard block) scaled by both
predicted load and forecaster reliability. B8.3 `ForecastAccuracyTracker`:
a bounded (predicted, actual) history plus a reliability weight scaled
against a naive "always predict the historical mean" baseline — an
accurate forecaster scores high, a consistently-wrong one scores low,
a fresh tracker with no evidence defaults to full trust rather than
false distrust. B8.4 `is_quiet_window`: true only when every recent
reading stayed below a threshold fraction of capacity.

**"Learn from all previous runs" — new `hearthmind/ml/cross_run.py`.**
`pool_examples_across_runs`/`discover_runs`: pools training examples
from every past-run archive found under a `runs_root` directory via a
caller-supplied `example_loader` per run — a corrupted/unreadable run
is skipped, not fatal, and each run is capped (uniform random sample)
both individually and in the combined total so one unusually large run
can't drown out every other one. Deliberately distinct from L5's
per-world continual-learning loop (`hearthmind/ml/lifelong.py`,
v1.34.172): L5 keeps ONE world's own Mind models learning across its
own lifetime and stays per-world by design (`docs/ML-ARCHITECTURE-
2026-08-01.md`'s guardrail #3 — weights are per-world state, and two
worlds should diverge, not converge); cross-run pooling is for models
that describe the MACHINE, not any one world's cognition — B8.1's
forecaster (this pass's first concrete consumer, and L3.2's own first
shipped instance) has no reason to start learning from nothing every
session just because it happens to run inside one particular world.
Verified end-to-end: a `WorkloadForecaster` trained on a pool
assembled from three synthetic past-run directories learns just as
well as one trained on a single run's data, and correctly keeps
contributing from every run even when one archive raises during
loading. Both `docs/ML-ARCHITECTURE-2026-08-01.md` (L3.1/L3.2 section)
and `docs/HEARTHBENCH-RUNTIME-2026-07-23.md` (B8) updated to record
this as the direct answer to the instruction.

**Not wired into any real control point** — no import from
`forecasting.py`/`cross_run.py` exists in `simulation/engine.py`/
`server.py`, no real recorder/metrics archive is ever fed through
`pool_examples_across_runs`, and `plan_reservation`'s output isn't
consulted by B2's real scheduler. Real future work, naturally paired
with B7's own unwired `select_strategy`/`GoodCitizenPolicy`.

One real bug caught and fixed during verification, not by the user:
the first version of the synthetic training check used raw-scale
features (backlog 0-10, target volume up to ~28) — plain SGD (no
batch-norm/Adam) reliably diverged to NaN at every learning rate tried,
including ones an order of magnitude below what every other check in
this codebase uses safely. Root cause: `MLP.random_init`'s weight scale
assumes roughly unit-scale inputs; un-normalized 0-10-range features
against that init blow up the first few gradient steps. Fixed by using
normalized ~[0,1]-scale synthetic features (what a real forecaster's
inputs would actually look like — fractions/rates, not raw unbounded
counts) rather than further lowering the learning rate, which alone
did not fix it. Documented at the call site rather than silently
tuned away.

Verified: `scripts/verify_forecasting.py` (29 checks — `discover_runs`/
`pool_examples_across_runs` correctness incl. per-run/total capping and
fault tolerance, the forecaster's real training + a correct learned
disaster→load correlation, cross-run pooled training, accuracy-tracker
reliability-weight direction in both directions plus the cold-start
default, `plan_reservation`'s monotonicity/capacity-bound/zero-
reliability cases, `is_quiet_window`'s single-spike-breaks-quiet case)
— all pass. `pyflakes` clean. `scripts/verify_runtime_invariant.py`/
`verify_task_graph.py`/`verify_scheduler.py`/`verify_dormancy.py`/
`verify_tuning.py`/`verify_hardware_profile.py`/`verify_ml_substrate.py`
re-run clean (unaffected). No native module, persisted `World` state,
or real engine code path touched — no soak re-run needed.

## Current state (v1.34.173)

Explicit user instruction: "Start tier 5 and you are allowed to use
PyTorch/tensorflow etc also." Two independent pieces, one batch.

**Tier 5's B7 — Hardware model, all four sub-items.** New
`hearthmind/simulation/hardware_profile.py`, same "never big-bang"
discipline as every prior Tier 5 Runtime module (task_graph.py,
scheduler.py, reactivity.py, dormancy.py, profiling.py, tuning.py) —
not wired into `simulation/engine.py`/`server.py`. B7.1 `HostProbe.
sample()`: logical + usable (`os.sched_getaffinity`, cgroup/taskset-
aware, same discipline as `setup.py`'s parallel-build core count)
cores, RAM total/available/swap (a fresh `/proc/meminfo` read, same
shape `engine.py`'s existing `system_memory_report()` already uses,
kept standalone rather than importing engine.py), 1-minute load
average, a 4 MiB storage write/read micro-benchmark, best-effort GPU
presence (`/proc/driver/nvidia`) and thermal state (`/sys/class/
thermal`, "throttled" past 90°C) — every field degrades to `None`
rather than raising when unavailable, a probe must never be able to
crash its caller. B7.2 `MachineProfile`: host-fingerprinted, every
measured field (LLM throughput, storage benchmark) is an exponential
moving average across sessions, not a flat overwrite — "gradually
evolves," verified directly; versioned JSON blob save/load, rejecting
an unsupported `schema_version`, same discipline as the ML weight
blobs. B7.3 `select_strategy`: a pure function over profile data
(never a hardware-specific branch in gameplay code, per the item's own
text) — verified a many-core/high-RAM host gets more LLM concurrency/
workers/cache than a modest one, and that memory pressure, active
swap, or thermal throttling all lower concurrency and raise dormancy
aggressiveness regardless of how beefy the raw hardware otherwise
reads. B7.4 `GoodCitizenPolicy`: `CONSERVATIVE`/`BALANCED`/
`AGGRESSIVE` back-off levels — verified a conservative policy backs
off at moderate memory pressure or any active swap while an aggressive
one tolerates both, and that extreme external load or thermal
throttling trigger back-off regardless of setting. NUMA nodes and true
physical-vs-logical core counts deliberately not distinguished (would
need a real dependency or manual sysfs topology parsing beyond this
pass's scope) — `usable_cores` is the honest, already-useful
substitute. Verified: `scripts/verify_hardware_profile.py` (29 checks)
all pass. `pyflakes` clean.

**Extended v1.34.171's dependency relaxation to deep-learning
frameworks.** `pyproject.toml` gained `ml-torch = ["torch>=2.2"]` and
`ml-tensorflow = ["tensorflow>=2.15"]`, kept separate from the
lightweight `ml` (numpy) extra so a numpy-only training pass never
pulls a multi-GB framework it doesn't need. Same contract as `ml`:
offline training only, never a runtime/inference dependency — the
shipped inference path stays stdlib + `cpp/src/` regardless of which
extras (if any) are installed. Neither extra is installed or exercised
by any code in this pass — reserved for a future Tier 6 model that
genuinely outgrows what L0's small MLP primitives can express (e.g.
L1.1's embedding at real vocabulary scale), not adopted speculatively.
`docs/ML-ARCHITECTURE-2026-08-01.md`'s guardrail #7 and `docs/ML-
AUDIT-2026-08-01.md`'s guardrail #6 both updated to record this.

`scripts/verify_runtime_invariant.py`/`verify_task_graph.py`/
`verify_scheduler.py`/`verify_dormancy.py`/`verify_tuning.py`/
`verify_ml_substrate.py` re-run clean (unaffected). No native module,
persisted `World` state, or real engine code path touched — no soak
re-run needed.

## Current state (v1.34.172)

Explicit user correction: "Also your ML arch and audit is missing
lifelong learning: closes the loop so worlds continue to diverge over
years of simulated time and automated learning." Real gap, not a
nitpick — v1.34.170/.171's "weights are per-world state" claim only
ever made two worlds diverge AT TRAINING TIME; nothing in either ML
doc described a mechanism that kept a world's models actually learning
across the years of simulated play that follow a training pass.

Adds a new **Layer 5 — the lifelong learning loop** to
`docs/ML-ARCHITECTURE-2026-08-01.md` (and a cross-referencing note in
`docs/ML-AUDIT-2026-08-01.md`'s guardrail #2, which is where the
"weights diverge" claim originally lived): L5.1 a continual-retrain
cadence keyed to SIMULATED time (season/year boundaries, same
convention as `SEASON_YEAR_JOBS_WITH_RETRY`), async and never blocking
the tick loop; L5.2 warm-start + replay rehearsal — a retrain fine-
tunes a model's EXISTING weights on new examples mixed with a
reservoir-sampled slice of its whole training history, never
reinitializing from scratch; L5.3 a shadow-evaluation swap gate — a
candidate retrain must not regress the live model's held-out metric
before replacing it, B15's "no judgment call on a regression" rule
applied to model quality; L5.4 a bounded, versioned per-world
checkpoint history with rollback.

Ships L5.1-L5.4 as real, verified, standalone primitives — same
"never big-bang" discipline as L0: new `hearthmind/ml/lifelong.py`
(`ReplayBuffer` — Algorithm-R reservoir sampling, `CheckpointHistory`,
`passes_shadow_gate`) and `hearthmind/ml/training.py`'s new
`continual_train_mlp` (warm-start training mixing fresh examples with
replay-buffer rehearsal). **Not wired to any real retrain cadence or
`simulation/engine.py` call site** — needs a real per-model decision of
what "new examples since last retrain" means concretely, plus the
still-unbuilt B1/B2 scheduler actually migrated into the live tick
loop first; explicitly flagged, naturally sequenced alongside L2.2
phase 2 once that exists to retrain.

One real bug caught and fixed during verification, not by the user:
the first version of the catastrophic-forgetting proof (`scripts/
verify_ml_substrate.py`) trained a mixed old-task+new-task batch at
`learning_rate=0.05` — the same rate every single-task check in this
file already uses safely — and reliably diverged to NaN. Traced to
plain SGD (no momentum/clipping) on two orthogonal regression targets
in one combined batch being a measurably harder optimization landscape
than either task alone; `learning_rate=0.01` converges stably and the
divergence is documented in a comment at the call site rather than
silently tuned away.

Verified: `scripts/verify_ml_substrate.py` extended 17 -> 27 checks
(new: reservoir-sampling retention probability matches the exact
Algorithm-R theoretical value — item 1's survival rate after n
insertions is capacity/n — within tolerance over 3000 trials;
checkpoint history bounds/latest/rollback incl. the empty-history
no-op case; shadow-gate accept/reject/tolerance/equal-metric cases;
and the load-bearing check — a model continually retrained WITHOUT
replay loses >50% of its old-task accuracy relative to baseline, one
retrained WITH replay recovers to within half of that lost ground
while still genuinely learning the new task, measured against a
not-learned-at-all reference point) — all pass. `pyflakes` clean.
`scripts/verify_runtime_invariant.py`/`verify_task_graph.py`/
`verify_scheduler.py`/`verify_dormancy.py`/`verify_tuning.py` re-run
clean (unaffected). No native module, persisted `World` state, or real
engine code path touched — no soak re-run needed.

## Current state (v1.34.171)

Explicit user instruction: "Please allow the use of external
libraries, don't make anything unimplementable just because external
libraries can't be installed. Also continue with tier 5." Relaxes the
stdlib-only/no-new-runtime-dependency constraint both
`docs/ML-AUDIT-2026-08-01.md` and `docs/ML-ARCHITECTURE-2026-08-01.md`
had self-imposed (the constraint was never a real environment limit —
`pip install numpy` succeeds cleanly here; confirmed before changing
anything). Both docs' guardrail sections rewritten: external libraries
(numpy) are now permitted for **offline training only**; the shipped
**runtime inference path stays stdlib-only** regardless, same
contract every native `cpp/src/` module already honours (missing/
absent dependency degrades to the existing fallback, never a crash).
New `pyproject.toml` optional extra, `ml = ["numpy>=1.26"]` — kept
separate from `dependencies`/`api`/`bench` so the live server never
requires it, same isolation discipline as Tier 5's own `bench` extra.

Ships Tier 6's **L0 substrate** (docs/ML-ARCHITECTURE-2026-08-01.md),
the first real Tier 6 code — "continue with tier 5" read in the ML/
Tier-6-implementation context the immediately preceding several turns
were in, since the "allow external libraries" half of the same
instruction only makes sense there (the literal remaining Tier 5
Runtime items, B7+, need no external library). New `hearthmind/ml/`:
`encoder.py` (`FeatureSchema`/`FeatureEncoder` — deterministic
numeric + one-hot categorical vectorization, the shared vector shape
every Layer 1+ model will consume, per the architecture doc's own
"adding a model is adding a head, not a pipeline" framing);
`primitives.py` (`LinearLayer`, `MLP` — 1-3 layer, ReLU hidden,
linear/sigmoid/softmax output heads, `PlattCalibrator` — L4.1's own
"deliberately not a network" calibration primitive — all pure-Python
inference, a versioned JSON weight-blob `save`/`load`); `training.py`
(a pure-Python full-backprop SGD trainer — the reference
implementation — plus an optional numpy-accelerated batch forward
pass, `HAS_NUMPY`-gated, that raises `RuntimeError` rather than
silently degrading when numpy is absent). A C++ forward pass is
deliberately NOT built yet — this ships the Python reference and
training harness only; porting to `cpp/src/` is real future work once
an actual consumer (L1.1/L2.x) exists to justify the port, same
"don't build inference speed before there's a model to serve"
discipline every other native-port decision in this project follows.
**Not wired into any live gameplay code** — same "never big-bang"
discipline as every Tier 5 Runtime module; no import from
`hearthmind/ml/` exists anywhere in `simulation/engine.py`.

Verified: `scripts/verify_ml_substrate.py` (17 checks — encoder
correctness incl. missing/bad-value degrading to 0.0 rather than
raising, hand-computed linear/MLP forward passes, softmax sums to 1,
weight-blob round-trip incl. rejecting an unsupported
`schema_version`, a Platt calibrator fit genuinely separating two
score bands, the SGD trainer cutting loss >90% on a learnable toy
regression, and the load-bearing check for this pass — the
numpy-accelerated batch forward pass is equivalent to the pure-Python
forward pass within 1e-9 for both a sigmoid and a softmax output head)
— all pass with numpy installed; the numpy-dependent checks degrade to
a clean `[SKIP]`, not a failure, when the `ml` extra isn't installed,
and a dedicated check confirms `numpy_batch_forward` raises cleanly
(not a silent fallback) when called without numpy. `pyflakes` clean.
`scripts/verify_runtime_invariant.py`/`verify_task_graph.py`/
`verify_scheduler.py`/`verify_dormancy.py`/`verify_tuning.py` re-run
clean (unaffected — `hearthmind/ml/` sits outside every directory
`verify_runtime_invariant.py` scans). No native module, persisted
`World` state, or real engine code path touched — no soak re-run
needed.

## Current state (v1.34.170)

Explicit user instruction: a final architecture pass over v1.34.169's
audit before implementation — challenge every proposed model, merge
only where there's clear architectural benefit, avoid both
fragmentation and over-generalization, and extend with distillation,
outcome/reward learning, semantic retrieval, planning policy,
attention, runtime prediction, social learning, and belief calibration.
**Docs-only.** Final architecture: `docs/ML-ARCHITECTURE-2026-08-01.md`
(the audit stays the baseline evidence; the architecture doc is what to
build). Roadmap Tier 6 rewritten to match.

**9 loose stages -> 4 layers / 8 models**, with three shared components
(feature encoder, semantic embedding, value head) that most of the rest
reuse.

**Four things removed or demoted, each for a stated reason** — this is
the part worth remembering, since each was in the audit's own plan:
(a) the learned *task*-cost model: `TaskMetrics.mean_wall_seconds()`
already computes it, so feeding it to `cost_hint` is plumbing, not
learning — calling it a model would be theater; (b) a separate planning
model: `Agent.plan` maps onto the same closed `AgentGoal` set the
policy already outputs, so it folds in as an embedded input feature;
(c) a neural belief-confidence model: calibration (isotonic/Platt) is
the right tool for a 1-D problem, and a network there is exactly the
unnecessary generalization this pass exists to remove; (d) the full
social GNN: `world/graph_algorithms.py` ALREADY ships `build_
relationship_graph`/`degree_centrality`/`bfs_distances` — the real gap
is that nothing feeds those to the decision models, so this became a
1-layer message-passing FEATURE EXTRACTOR (L1.2), with end-to-end graph
learning explicitly deferred rather than built speculatively.

**Two merges, each because it's literally the same computation asked
twice:** the audit's M3-consumer + M4 became one learned retrieval
scorer (learning combination weights over a frozen bag-of-words
relevance term, or a good embedding under hand-set weights, each leaves
half the win unclaimed); and attention allocation + policy advantage
weighting now share one **value/consequence head** (L2.1) trained on
`emergence.magnitude` + downstream `life_events`. The *ranking* and
*action* logic stay separate — different problems.

**The biggest design change is L2.2's two-phase curriculum**, the
extension the instruction asked for and strictly better than either
half alone: phase 1 distills the recorder's existing `(structured_
input -> goal)` pairs (teacher->student, no cold start, no hand-written
ladder); phase 2 reweights by realized world outcome so the student can
**diverge from and exceed the teacher** where the world says the LLM was
wrong. That second phase is where genuine per-world divergence comes
from — two worlds with different histories reward different policies,
so their agents think differently because of what happened to them, not
because of a seed. Pure imitation caps at the teacher; a fixed ladder
can't do it at all.

**Homogenization is named as the hard risk and designed against**, not
just flagged: one shared policy would make every agent think alike —
precisely the failure mode v0.88.0 fixed for traits. Three mandatory
mitigations: personality-conditioning (one net, different behavior per
agent state), an entropy floor (never argmax), and survival overrides
staying deterministic and untouched. Per-agent networks were explicitly
rejected — conditioning solves this, 300 networks is fragmentation.

**One further guardrail added this pass:** never train a model on its
own unweighted outputs. Phase 1 uses LLM-authored decisions only; phase
2 admits the student's own decisions ONLY weighted by realized
outcomes. That's the guard against self-reinforcing collapse.

Model weights are **per-world state**, snapshotted — that's the
emergence mechanism, and it's also what keeps `verify_replay_hash.py`
meaningful (same seed + same weights = same result).

## Current state (v1.34.169)

Explicit user instruction: audit the whole repo (code + docs) for every
current and planned LLM task, decide what genuinely needs an LLM vs.
what can be a deterministic algorithm or specialized AI/ML (ANNs, GNNs,
RL, boosting, evolutionary, symbolic); also find deterministic systems
with high emergence/sentience potential that should instead learn;
produce a prioritized plan and update the roadmap. **Docs-only — no
code changed.** Full audit: `docs/ML-AUDIT-2026-08-01.md`; the staged
plan is tracked as the roadmap's new **Tier 6** (M0-M9).

**This corrects v1.34.168's finding, which was too broad.** Two of its
three arguments were wrong, and the error is worth recording so it
isn't repeated: (1) "a trained classifier is the same category of thing
as the hand-authored rule system already rejected" is false — a model
trained on *this world's* accumulated history encodes that world's
lived statistics and diverges between worlds, which is a mechanism FOR
emergence; the standing "don't replace LLM reasoning with a rule
system" rule was written against hand-authored rules and doesn't reach
learned models. (2) "no labeled ground truth exists" is contradicted by
this repo's own code — `llm/recorder.py` has recorded
`layer1_structured_input` -> `layer4_parsed_output` plus `latency_ms`/
`fallback_used` since v0.87.28, and `persistence/database.py:98`'s
`metrics` table is a per-tick persisted time series. Both are real
supervised datasets. Only the third argument survives: most `llm/`
modules are free-text generation, and that still governs the majority
of the surface.

**Feasibility, which is what makes this actionable:** the "no training
infrastructure" objection applies to LoRA-fine-tuning a 4B LLM (still
correctly out of scope, unchanged from v1.34.159). It does NOT apply to
small task-specific models. The viable shape is train offline -> ship
weights as data -> infer in C++ with a pure-Python fallback, exactly
what all 24 `cpp/src/` modules already do. Zero new runtime dependency.

**Hard boundary, unchanged:** dialogue, chronicle/folklore/legend,
naming, world genesis, and the entire ontology-expansion family
(`ontology`, `invention`, `rule_propose`, `composite_reaction_propose`,
`species_variant`, `nature_mind`) stay LLM-authored. A classifier can
only choose among classes it was trained on — the exact opposite of
what `world/ontology.py`'s registry exists to do.

**Flagship findings** (all evidence-cited in the audit doc): (a)
`cognition`'s output is `{goal: one of 7 closed values, reason: free
text}` — a clean split, where the goal half is a classification the
recorder already has training pairs for, and replacing
`fallback_goal`'s hand-written if-ladder would give the WHOLE
population learned judgment instead of a fixed ladder (more agents
thinking, not fewer); (b) `retrieve_relevant_memories` is already a
linear model with three hand-set weights and a bag-of-words relevance
term — one learned embedding would upgrade it plus `pillar.
word_overlap` and four dedup sites at once; (c) `Task.cost_hint` is a
hand-set `1.0` even though B5 now measures the real number; (d) B2.4
("attention follows change") has been blocked on exactly the learned
priority model M6 proposes.

## Current state (v1.34.168)

Explicit user instruction: "Start B6 and audit the code for current
and future implementations to see if some LLM jobs can be replaced by
true AI/ML applications like neural nets etc. maybe for adaptive
runtime too" (docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Tier 5).

**B6 — adaptive tuning.** New `hearthmind/simulation/tuning.py`:
B6.1's `Tunable`/`TunableRegistry` (real min/max/step + a `SafetyClass`
of `SAFE`/`SENSITIVE`, `adjust`/`set_value` always clamp — verified
directly, repeated over-adjustment never overshoots either bound);
B6.2's `BangBangController` (deterministic feedback control with a
real hysteresis dead-zone — several in-band readings produce zero
change, the mechanism that stops a controller chattering; "PID-ish or
bang-bang" per the item's own text, bang-bang chosen as the simpler,
more directly testable of the two); B6.3's `register_llm_pacing_
tunables` registers the real existing `llm_pressure_*`/`llm_max_
concurrent` constants (this file's own long-documented lineage) as a
real tunable set under the general framework — metadata only, does
NOT rewire `engine.py`'s actual pacing code, which needs the same
live-diagnostic verification every past retune of these exact
constants has needed, not something to flip blind. `scripts/verify_
tuning.py` (6 checks, including both bang-bang direction polarities)
all pass. Not wired into any real control point, same discipline as
every prior B-item.

**The LLM/ML-candidate audit** (docs-only, no code changed as a
result): reviewed all ~45 modules under `llm/` plus Part B's own text.
Three independent findings converge on the same answer — nothing in
this codebase should be replaced by a trained model right now:

1. **Most `llm/` jobs are free-text generation** (dialogue, chronicle,
   folklore, legend, letters, dream, omens, religion, naming, world_
   genesis, ...) — a classifier/regressor cannot generate prose; the
   only model class that could is another generative model, i.e.
   still "an LLM," not a different category of ML.
2. **The remaining structured-decision jobs are exactly the ones this
   project already has a standing, explicit rule against automating
   away**: "Everything involving judgement, interpretation, creativity,
   uncertainty, psychology, or social behavior should default to the
   local LLM... don't replace LLM reasoning with a large deterministic
   rule system just because it's easier to implement" (see "Design
   priorities" above). A trained classifier is architecturally the
   same category of thing as the deterministic-rule-system alternative
   already rejected for these decisions — a fixed, non-emergent
   decision function — for the exact reason emergence tops this
   project's own priority order. The v1.3.35 batch already did the
   real available migration in the OTHER direction: LLM calls that
   were actually objective/computable got converted to deterministic
   Body values with the LLM narrating, not vice versa; nothing found
   this pass reopens that boundary.
3. **No training infrastructure or labeled ground truth exists, and
   this is an explicit standing decision, not an oversight**: v1.34.159
   already declined a real LoRA/fine-tuning pipeline ("no torch/peft/
   transformers, this environment has no training infrastructure and
   none was added") and `llm/eval_harness.py`'s `training_readiness_
   report` already exists specifically to say "not enough labeled
   volume yet" per task (`MIN_SFT_EXAMPLES_PER_TASK=200`) — the
   tooling to notice when this becomes viable already exists and
   already reports it isn't yet.

**For the Adaptive Runtime specifically**, the source doc had already
independently reached the same conclusion before this audit: B6's own
text says "Deterministic, no LLM... evolutionary algorithms,
statistics, optimization, feedback control," and the only ML-adjacent
technique named anywhere in Part B is B13.5's "optional evolutionary
search over tunable sets" — explicitly optional, explicitly gated
behind B13.1/B13.2 (a hypothesis-loop + replay-hash safety gate) being
solid FIRST. This isn't an oversight to fix; it's the right call for
this specific system: B15's core safety guarantee ("a performance win
that changes outcomes is automatically rejected, no judgment call")
is far easier to bound and verify for an interpretable bang-bang
controller with a known worst-case step than for a trained black-box
model's decision boundary. Building B13.5 later remains real,
legitimate future work — flagged, not built this pass (B13 itself is
entirely unbuilt).

**One real, narrow opportunity flagged for a future pass, NOT built
here**: `llm/quality_labels.py`/`eval_harness.py` are HearthBench's
existing rule-based (not ML) scorers (A4's "Tier 1: deterministic
scorers"). A stdlib-only linear/logistic classifier trained offline on
the recorder archive, used purely to pre-screen completions before a
human or judge-model review, would stay within HearthBench's scoring
domain (already explicitly an evaluation concern, not a live
simulation decision) and would need zero new dependency — but needs
real labeled outcome data this project doesn't have yet either. Not
attempted this pass; a genuinely different judgment from "replace a
live cognition decision with a trained model," which the audit found
no case for anywhere.

Verified: `scripts/verify_tuning.py` (6 checks — duplicate-name
rejection, clamping in both directions, bang-bang basic direction, the
inverted-polarity case proving the direction flag is load-bearing, the
hysteresis dead-zone, and the real B6.3 tunable set) all pass.
`scripts/verify_scheduler.py`/`verify_task_graph.py`/`verify_
dormancy.py`/`verify_hearthbench_isolation.py`/`verify_runtime_
invariant.py` re-run clean (unaffected). `pyflakes` clean on the new
module and script. No native module, persisted `World` state, or real
engine code path touched — no soak re-run needed.

## Current state (v1.34.167)

Explicit user instruction: "Continue B5" (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Tier 5). New `hearthmind/simulation/profiling.py`:
B5.1's `TaskMetrics` (call/error/skipped/deferred/promoted/spare-
capacity counts, a bounded wall-time ring buffer, derived `idle_
ratio()`) and B5.4's `TickTrace`/`TaskTraceEntry`. `Scheduler` now
creates a `TaskMetrics` entry for every task the moment it's first
processed — no registered task can escape being metered, which is the
real structural version of B5.3's "no subsystem may be a black box"
review rule (no CI exists in this repo to add that rule to anyway).
`run_tick` builds a full `TickTrace` EVERY tick (not an opt-in
profiling mode) with a specific reason string per task explaining
which trigger fired and why — e.g. "ON_DIRTY: reads ['soil'] changed
since last observed", "budget exhausted for 'x' (remaining=
0.000000s)", "deferral bound reached (3 >= 3) -- force-run" — appended
to a bounded 500-tick ring buffer (`Scheduler.tick_traces`). Built in
the same pass as the B2/B3 scheduling logic it explains, honoring the
item's own "build it with B1, not after" instruction rather than
bolting it on later. `EventBus` gained a small additive `pending()`
accessor the tracer needs to name which event(s) made an `ON_EVENT`
task due.

B5.2's overhead is measured, not assumed: a new verification check
times 50 synthetic tasks x 200 ticks under the real `Scheduler`
against the same functions called bare, and prints the real per-task-
tick overhead (~12us on this environment) — "a profiler that costs 5%
must say so" now has a real number attached, with a sanity bound that
would catch a future accidental O(n²) regression.

**B5.3 (a real `/diagnostics/runtime` endpoint + dev-console wiring)
explicitly NOT attempted** — no real engine subsystem runs through
`Scheduler` yet to expose. **B5.4's own second half (an on-demand
"trace next tick in full detail" toggle for something heavier than the
always-on trace) also NOT built** — at this module's current
abstraction there's no real task-argument/state snapshot to make a
"more expensive" capture mode meaningfully different from what's
already always-on; a toggle doing nothing extra would be theater.

Verified: `scripts/verify_scheduler.py` extended 10 checks -> 13 (new:
per-task metrics track real call/deferred/promoted counts and a
correct `idle_ratio()` across several ticks; a tick's trace records
every task's real outcome and a specific correct reason including the
promoted/spare-capacity cases; the instrumentation overhead check
above) — all 13 pass. `scripts/verify_task_graph.py`/`verify_
dormancy.py`/`verify_hearthbench_isolation.py`/`verify_runtime_
invariant.py` re-run clean (unaffected). `pyflakes` clean on all new/
touched modules (only the four known pre-existing `engine.py` findings
elsewhere, already confirmed harmless). No native module, persisted
`World` state, or real engine code path touched — no soak re-run
needed.

## Current state (v1.34.166)

Explicit user instruction: "Start B4" (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Tier 5). New `hearthmind/simulation/dormancy.py`'s
`DormancyManager`: B4.1's real `ACTIVE -> DROWSY -> DORMANT ->
ARCHIVED` lifecycle (`is_scheduled()` reads False only for DORMANT/
ARCHIVED — DROWSY stays scheduled, since the doc's own spectrum
implies reduced attention, not zero, and B2.4's attention-follows-
change, the real lever for that distinction, doesn't exist yet).
B4.3's lossless-wake contract is baked directly into the API rather
than left as a discipline to remember: `wake()` is the ONLY way to
leave DORMANT/ARCHIVED and it ALWAYS returns the real elapsed-tick gap
the entity was unscheduled for (0 for a safe no-op on an already-
active entity) — a caller can ignore the return value, but can't
accidentally not receive it. A second `sleep()` call while already
dormant is a no-op that preserves the original clock, not a reset.

B4.4's chaos-testing technique: `scripts/verify_dormancy.py`'s
`check_chaos_dormancy_matches_no_dormancy_baseline` runs 20 random
seeds x 500 ticks of force-sleep/wake against a synthetic accumulator
entity (random sleep at 10%/tick while active, random wake at 20%/
tick while dormant, a final forced wake to flush pending state), each
seed asserted to produce the exact same final value as a no-dormancy
baseline — proving the elapsed-time catch-up integration is genuinely
lossless under adversarial random timing, not just in straight-line
lifecycle checks. Since no real B4.2 candidate exists yet to point a
real replay-hash chaos test at, this demonstrates the technique
itself; the same approach applies directly to `scripts/verify_
replay_hash.py`'s real hash once one does.

**B4.2 (the five named real candidates — forgotten traditions,
inactive settlements, distant wildlife, unused ideas, idle
institutions) explicitly NOT attempted** — each needs real, live-
tested sleep/wake criteria touching actual `world/`/`agents/`/
`settlement/` gameplay code, the same "one subsystem at a time, never
big-bang" discipline B0.3/B1.4/B3.3 all deferred for the same reason.
`DormancyManager` is ready for the first one to use whenever that
migration starts. "State compressed" from B4.1's own text is also not
built — that's B12 (state compression), which doesn't exist yet; same
honest-placeholder discipline as B2.1's "adaptive (B6)."

Verified: `scripts/verify_dormancy.py` (8 checks — lifecycle state
transitions, correct elapsed-tick counts, safe no-op wake on an
already-active entity, ARCHIVED symmetric with DORMANT, a repeated
sleep() call preserving the original clock, and the 20-seed chaos
test) all pass. `scripts/verify_scheduler.py`/`verify_task_graph.py`/
`verify_hearthbench_isolation.py`/`verify_runtime_invariant.py`
re-run clean (unaffected). `pyflakes` clean on both new files. No
native module, persisted `World` state, or real engine code path
touched — no soak re-run needed (this module has no real gameplay
consumer yet).

## Current state (v1.34.165)

Explicit user instruction: "start B3" (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Tier 5). New `hearthmind/simulation/reactivity.py`:
B3.1's `DirtyTracker` (a monotonic per-key write-VERSION counter, not
a plain boolean flag — lets several independent `ON_DIRTY` readers of
the same key each observe one write exactly once, on their own
schedule, without racing to clear a shared bit first) and B3.2's
`EventBus` (one-shot per-tick publish/subscribe — `clear()` at tick
end drops any unconsumed event, deliberately distinct from
`DirtyTracker`'s persistent state: "did this happen" has no "still
pending" concept once its tick has passed). `Task` gained an additive
`event_types: frozenset[str]` field for `ON_EVENT` subscriptions
(default empty — every pre-B3 `Task`, including every `Task.
legacy(...)`, unaffected).

`Scheduler.run_tick` now gates EVERY task (before any B2 budget/
priority logic, all priority classes including CRITICAL) on a real
`_is_due` check: an `ON_DIRTY` task with clean reads, or an `ON_EVENT`
task whose event wasn't published this tick, is `skipped_clean` —
never touches the budget/deferral machinery at all, which is B3.1's
own named "single biggest CPU win." `PERIODIC` (and `PREDICTED`, not
specially handled — flagged honestly) tasks stay unconditionally due,
unchanged from B2's original behavior.

**B3.3 (audit + convert the ~200 real per-tick polling call sites in
`engine.py`) explicitly NOT attempted** — a real case-by-case audit
needing individual judgment and live replay-hash verification per
conversion, not a mechanism to build; same shape as B1.4's actual
subsystem migration, real future work.

**Still not wired into the live tick loop** — no import from
`reactivity.py` exists in `simulation/engine.py`; both primitives have
only ever been exercised against synthetic task sets.

Verified: `scripts/verify_scheduler.py` extended 5 checks -> 10 (new:
an `ON_DIRTY` task never fires with nothing written, fires exactly
once after a write, goes clean again immediately after; two
independent `ON_DIRTY` readers of the same key each observe one write
exactly once; an `ON_DIRTY` task with no declared `reads` never fires;
an `ON_EVENT` task only fires on the tick its event was published, not
before or after; `DirtyTracker`/`EventBus` exercised directly) — all
10 pass. `scripts/verify_task_graph.py`/`verify_hearthbench_
isolation.py`/`verify_runtime_invariant.py` re-run clean (unaffected).
`pyflakes` clean on all new/touched modules. No native module,
persisted `World` state, or real engine code path touched — no soak
re-run needed.

## Current state (v1.34.164)

Explicit user instruction: "continue tier 5 with B2" (docs/
HEARTHBENCH-RUNTIME-2026-07-23.md). New `hearthmind/simulation/
scheduler.py`'s `Scheduler`, built on B1's `TaskRegistry`: B2.1's
per-subsystem `SubsystemBudget` (real wall-clock via `time.perf_
counter()`, static — "adaptive" needs B6, which doesn't exist, so
this stays honest rather than faked); B2.2's bounded-deferral priority
classes (`DEFAULT_MAX_DEFERRALS` per `PriorityClass` — a task hitting
its bound is force-run and flagged `promoted`, guaranteeing no
starvation; CRITICAL always runs); B2.3's overrun policy (a task over
its subsystem's budget is DEFERRED not skipped, `SubsystemBudget.
debt_seconds` accrues real overrun and never silently resets); B2.5's
work-conserving pass (`run_tick`'s optional `tick_time_budget_seconds`
runs deferred BACKGROUND/IDLE_ONLY work within the SAME tick when
genuinely spare overall time exists, `TickReport.ran_via_spare_
capacity`, without touching another subsystem's own budget). B2.4
explicitly skipped — its own text requires B10's timescales and B11's
locality "to be honest," neither exists yet; faking a per-region
activity score without them would be a guess dressed as a feature.

`TaskRegistry` gained one small additive accessor, `get(task_id)`
(read-only, needed by the scheduler to resolve ids from `topological_
order()` back to real `Task` objects) — B1's own shipped behavior is
otherwise untouched.

**Not wired into the live tick loop this pass** — same discipline as
B1: no import from `scheduler.py` exists in `simulation/engine.py`,
and the scheduler has only ever run against synthetic tasks. Real
infrastructure a future subsystem migration will use, not the
migration itself.

Verified: `scripts/verify_scheduler.py` (5 checks — CRITICAL always
runs even at zero budget, a STANDARD task over budget is deferred not
skipped, a DEFERRABLE task hitting its deferral bound is force-run and
flagged promoted, overrun debt persists and strictly increases across
sustained-overrun ticks, a deferred BACKGROUND task runs within the
same tick once spare overall time is given) all pass; `scripts/verify_
task_graph.py` and `scripts/verify_hearthbench_isolation.py` re-run
clean (unaffected); `pyflakes` clean on both new/touched modules. No
native module, persisted `World` state, or real engine code path
touched — no soak re-run needed.

## Current state (v1.34.163)

Explicit live-report bug fix: "sometimes the map in UI becomes big
occupying the whole screen and then clicking somewhere restores it to
its original display state." Root cause found in `resizeCanvasDisplay`
(`app.js`, the v1.34.33 responsive-canvas redesign): it derived the
map's available CSS width from `#map-panel`'s own live `getBoundingClientRect().left`
— but `#map-panel` and `#sidebar` are `main`'s flex-wrap siblings, so
the panel's position is itself a RESULT of whether the sidebar has
wrapped below it this frame, which is itself a result of the map's
current width. A genuine feedback loop: once `#sidebar` wraps below
for any reason (a borderline window width), `panel.rect.left` collapses
toward the page edge, `availW` balloons toward the full window width,
the map grows to fill the screen, and the sidebar stays wrapped —
self-reinforcing until an UNRELATED reflow (a click opening/closing an
inspector panel, matching the live report exactly) happens to break
the loop and it snaps back to the normal side-by-side layout. Fixed by
measuring `main`'s own box instead (stable — a block container's width
doesn't depend on how its own flex children wrap) and reserving a
fixed budget for the sidebar (`#sidebar`'s own CSS `min-width: 280px`
plus `main`'s flex gap) rather than reading a position coupled to the
very layout decision being computed.

Verified live via Playwright: swept the viewport width from 1400px
down to 600px and back (crossing the wrap threshold repeatedly) —
canvas CSS width now tracks window width smoothly with no runaway
growth at any point, including while wrapped. At a borderline width
(700px), six repeated clicks produced byte-identical canvas sizes
(372px every time) — confirming the instability is gone, not just
less frequent. `node --check` clean.

## Current state (v1.34.162)

Explicit user instruction: "start B1" (docs/HEARTHBENCH-RUNTIME-
2026-07-23.md, Tier 5). New `hearthmind/simulation/task_graph.py`:
B1.1's `Task` frozen dataclass (id/subsystem/fn/timescale/
priority_class/reads/writes/trigger/cost_hint/locality/determinism,
plus new `TriggerKind`/`Locality`/`Determinism`/`PriorityClass` enums
— the last a placeholder vocabulary until B2's scheduler exists to act
on it), B1.2's `TaskRegistry` (builds a real dependency graph from
declared `reads`/`writes` overlaps, rejects a genuine cycle at build
time via `CycleError` rather than silently), B1.3's `topological_
order()` (Kahn's algorithm always picking the lexicographically
smallest ready task id — deterministic and registration-order-
independent, verified directly by registering the same tasks in
reverse order and confirming byte-identical output), and B1.4's
`Task.legacy(id, subsystem, fn)` — the incremental-adoption shim an
un-migrated call site can use as-is, carrying a wildcard write that
conflicts with everything so it always stays in a real, stable total
order relative to every other task rather than being silently
reordered.

**Deliberately NOT wired into the live tick loop this pass** — no
import from `task_graph.py` exists anywhere in `simulation/engine.py`,
and none of the ~200 real schedule points there were touched. B1.4's
own text is explicit ("never big-bang"): this ships the graph/
registry/ordering machinery and the shim mechanism a future per-
subsystem migration will use, not the migration itself. That migration,
and B2's budgeted scheduler that would actually execute a
`TaskRegistry`'s tasks, remain fully open.

Verified: `scripts/verify_task_graph.py` (5 checks — disjoint tasks
never gain a spurious ordering constraint, a real read/write dependency
imposes the correct direction regardless of registration order, a
genuine cycle is detected and rejected, topological order is fully
deterministic across reversed registration order, two legacy-shimmed
tasks always land in a stable total order) all pass; `pyflakes` clean
on the new module and script (only the four known pre-existing
`engine.py` findings elsewhere, already confirmed harmless). No native
module, persisted `World` state, or real engine code path touched — no
soak re-run needed.

## Current state (v1.34.161)

Explicit user instruction: "start B0 and then also A0" (docs/
HEARTHBENCH-RUNTIME-2026-07-23.md, Tier 5). Both are checklist items
whose own text says "no new mechanism, formalize/enforce what's
already true" — this pass shipped real, verified work on that basis
rather than treating either as a no-op.

**B0 — the prime invariant.** B0.1: adopted as a written architectural
law, see "The Adaptive Runtime's prime invariant" above (placed right
after "Preserve absolutely," explicitly given the same enforcement
weight as the Body/Mind split per the item's own instruction). B0.2:
new `scripts/verify_runtime_invariant.py` (AST-based, same standalone-
script convention as every `verify_*` sibling — no unittest, no CI
pipeline exists in this repo to wire it into) bans `threading`/
`concurrent.futures` imports, `time.sleep(...)` calls, and Thread/
Timer/ThreadPoolExecutor/ProcessPoolExecutor construction inside
`world/`/`agents/`/`settlement/`/`economy/`. Confirmed clean against
the real tree (47 files, zero violations — this codebase was already
honoring the invariant informally) and confirmed to actually catch
every banned pattern against a synthetic test file, not just trivially
pass on clean code. B0.3 ("~200 schedule points still live inside
`engine.py`") is the item's own scoping note, not an action — recorded
in the new CLAUDE.md section as-is; migrating them onto a real B1 task
graph is future Part B work, unattempted.

**A0 — foundations to reuse.** Every A0.1-.4 claim re-verified
directly against current source rather than trusting the doc's prior
`[PARTIAL]` tag: `llm/client.py`'s `OllamaClient`/`LlamaCppClient`
behind `build_llm_client` (A0.1), `llm/eval_harness.py`'s `split_
holdout`/`build_golden_set`/`check_regressions` (A0.2), `llm/
recorder.py`'s real four-layer `TrainingRecorder` schema (A0.3), and
`llm/quality_labels.py`'s `schema_valid`/`check_leaks`/`length_in_
bounds`/`dialogue_responds`/`topic_novel`/`label_example` (A0.4) are
all real and exactly as described — all four confirmed, not stale.
The item's own "Rule" (a shared `hearthmind.cognition_contract`
package HearthBench imports from) stays genuinely open — lifting these
four pieces into an importable shared location is real A2/A4 forward
work, not something A0 itself builds.

**Tier 5 status.** 5 items shipped total: B15.1 (v1.34.102), A1.1/A1.2
(v1.34.160), A0 (confirmed)/B0.1/B0.2 (this pass). Next natural step,
not yet decided: A2 (model adapter layer, the first piece HearthBench
actually needs to run anything) or B1 (task declaration & the work
graph, B0's own direct successor) — resume on future explicit
direction naming one.

Verified: `python3 -m pyflakes scripts/verify_runtime_invariant.py`
clean; `scripts/verify_runtime_invariant.py` run directly (47 files,
0 violations) and re-run against a synthetic violating file (correctly
flagged every banned import/call); every A0 claim independently grepped
against real source line numbers before being marked confirmed. No
native module or persisted `World` state touched — no soak re-run
needed.

## Current state (v1.34.98)

Explicit user instruction: "Continue tier 0, try humans pillar
per-agent producer" — resolved v1.34.97's flagged dead-end by
building the missing piece instead of working around it. `_run_
personal_belief`'s apply() now mirrors into `humans_pillar.
world_model` (not just `.memory`), subject deliberately `target.
name` itself — Humans' own standing theory about a specific person,
revised in place across repeated Reflect() calls via `Pillar.find_
world_model_entry`. Humans pillar's first per-agent-keyed `world_
model` content ever. This unblocked two sites flagged unshippable at
v1.34.97: `_maybe_schedule_memory_drift`/`_maybe_schedule_noncore_
nudge` now weight target selection by `humans_pillar.subject_
confidence(agent.name)` (`HUMANS_PERSONAL_TARGET_LEAN_WEIGHT=0.4`,
same shape as `institution_belief`'s conversion). Tier 0 now at
seven real converted sites plus this new producer.

Verified: direct unit tests (revision-in-place, non-match neutral), a
production-path smoke test through the real `_run_personal_belief`
apply() confirming both formation and revision-in-place, a 30,000-
trial statistical weighting test, production-path smoke tests
through both scheduling functions driven via the real async tick
loop until each genuinely fired, a 4000-tick soak with clean
round-trip, `pyflakes` clean.

## Current state (v1.34.97)

Explicit user instruction: "Continue tier 0 52 mirror sites." Docs-
only — the honest finding this pass is a real dead-end, not a new
site. Extended the fifth site's search technique codebase-wide and
found two candidates sharing its exact shape (`_maybe_schedule_
memory_drift`/`_maybe_schedule_noncore_nudge`, both Humans-pillar-
owned uniform per-agent picks). Before implementing, enumerated every
`humans_pillar.upsert_world_model` call site directly and found
exactly one, whose subject is always the settlement's mood theme,
never an agent's name — unlike Village/Innovation pillars, Humans'
`world_model` has zero per-agent-keyed content anywhere. Weighting
either candidate by `subject_confidence(agent.name)` would be a
silent, permanent no-op, so neither was shipped. Re-confirmed (not
assumed) that this environment still can't empirically test pillar
content live: a 20,000-tick LLM-disabled soak produces zero pillar
world_model entries and zero institutions, since `_schedule_llm_job`
never fires without a live LLM server. Tier 0 stays at five real
converted sites; a genuinely different Humans-owned site, or a first
per-agent Humans world_model producer, remains open.

## Current state (v1.34.96)

Explicit user request: "fresh candidate spotted by inspection" (Tier
0). Found by re-scanning every `rng.choice(` in `simulation/engine.py`
for the tiebreak/soft-decision shape the first four sites use.
`_maybe_schedule_institution_belief`'s uniform target pick (which
institution gets examined this month) now weighs `village_pillar.
subject_confidence(institution.name)` — a different angle from the
first four sites (which all bias WHAT a decision concludes; this
biases WHICH candidate gets picked at all), same "never narrow the
pool, only weight it" discipline. `INSTITUTION_BELIEF_TARGET_LEAN_
WEIGHT=0.4` keeps every eligible institution's chance real.

One honest note: switching `rng.choice` to `rng.choices(weights=...)`
does NOT preserve exact RNG-consumption parity even at uniform
weights (verified directly) — a real difference from the first four
sites. Not a violation of anything: CLAUDE.md's own workflow rules
say determinism/reproducibility isn't required here; the docstring is
worded to claim only what's actually true (uniform distribution, not
byte-identical draws).

Verified: a direct RNG-consumption-difference check (documented, not
"fixed"), a 30,000-trial statistical distribution test, a production-
path smoke test through the real scheduling function, a 4000-tick
soak with clean round-trip, `pyflakes` clean.

## Current state (v1.34.95)

Explicit user instruction: "Start tier 0 and try finishing it," then
"Continue and ask questions if you are blocked." Tier 0's ~52
remaining mirror-write sites stay real, un-scoped, per-site judgment
work (re-audited this pass, no new safe candidate found beyond what's
recorded below — see docs/ROADMAP-2026-07-REMAINING.md's Tier 0
section for the per-function reasoning). Two pieces of real progress
landed instead.

Tier 0.5's D10 (long-horizon soak re-verification, previously killed
at ~10k ticks for lack of wall-clock budget): ran a real 60,000-tick
`World.tick()` soak to completion, flat ~11.5ms/tick pace, clean
round-trip. Closes D10's deterministic-substrate half only — every
pillar's `memory` stayed empty the entire run since `_schedule_llm_
job` never fires with LLM disabled (this environment's standing
limitation, same as D1-D4/D9); the "does digest-of-a-digest folding
stay coherent after many real rounds" question still needs a live
LLM server.

Tier 0's fourth conversion site, via explicit `AskUserQuestion`:
`_maybe_schedule_ontology_evolution`'s fitness-weighted parent pick
now also multiplies in `innovation_pillar.subject_confidence(concept.
name)` (`INNOVATION_EVOLUTION_LEAN_WEIGHT=0.3`) — a real, distinct
signal from `fitness_history` (measured adoption outcomes) since it
reads Innovation's OWN recorded confidence about that specific
concept. Unlike the first three sites (a final catchall tiebreak),
this multiplies into the primary selection signal itself — the
riskier shape the user explicitly approved, kept bounded so fitness
stays dominant. `pillar_lean=0.0` reproduces prior output exactly.

Verified: direct unit tests, a production-path smoke test through the
real scheduling function, a 20,000-trial statistical weighting test,
a 4000-tick soak with clean round-trip, `pyflakes` clean.

## Current state (v1.34.160)

Explicit user instruction: "make vehicles also appear in UI live map
(maybe a different color for npc when using a vehicle?)... add a
clickable inspector... Also start something from tier 5."

**Vehicle map/inspector UI.** Vehicles were already drawn on the map
(cart/raft as squares, mount/automobile/boat as claimed/unclaimed
diamonds) — the real gaps were a rider's own visual distinction and a
click-inspector. New `PERSONAL_VEHICLE_RING_COLOR` (`app.js`): a rider
of a claimed mount/automobile/boat now draws a matching-hued ring
around their own marker, reusing the exact same hex each vehicle kind's
own diamond already uses (a violet ring always means "riding a mount,"
everywhere on the map) rather than a new unrelated palette — composes
with, doesn't replace, the existing sick/immune/rundown health rings.
New `findVehicleAt`/`openVehicleInspector`, wired into the click
handler between agents and buildings; the "vehicle" branch of
`renderTargetInspector` lists every vehicle at a tile (a worksite can
accumulate several over a settlement's life), showing kind/stage/
progress-or-condition/material (new `VEHICLE_MATERIAL`, mirrors
`world.materials.VEHICLE_MATERIALS`, same "Built of X — repair-speed
hint" line the building inspector already has)/current rider (personal
kinds only)/a plain-language mechanical-effect blurb per kind. Verified
live via Playwright against a seeded demo world: rider ring rendered
correctly, automobile inspector showed "ready · condition 34% · Built
of metal — repairs at an ordinary pace · Ridden by Osric" correctly.

**Tier 5 A1.1/A1.2 shipped** (`docs/HEARTHBENCH-RUNTIME-2026-07-23.md`).
New `hearthbench/` package (sibling of `hearthmind/`): 9 reserved
submodules (`runner/`/`adapters/`/`prompts/`/`tests/`/`validation/`/
`metrics/`/`diagnostics/`/`reporting/`/`ui/`), each an `__init__.py`
naming its own future spec item, no logic yet — the doc's own A1.1
skeleton. `pyproject.toml` gained a `bench = []` extra and
`hearthbench*` in `packages.find`. New `scripts/verify_hearthbench_
isolation.py` (A1.2, same standalone-script convention as `verify_
native_soak.py`/`verify_replay_hash.py`, no unittest): AST-walks every
`.py` file under both packages, asserting `hearthbench` never imports
`hearthmind.simulation`/`.agents`/`.world` and `hearthmind` never
imports `hearthbench` — confirmed clean (10 hearthbench files, 129
hearthmind files, zero violations either direction). This is the real
mechanical enforcement the brief's "the simulation should never know
anything about HearthBench" asks for, not just a convention.

**Tier 5 status, what's left** (see docs/HEARTHBENCH-RUNTIME-2026-07-23.md
for the full spec): of 30+ items, **2 shipped this pass (A1.1/A1.2)
plus B15.1 (v1.34.102)** = 3 total. Everything else is unstarted:
Part A (HearthBench) — A0 (formalize existing reuse, no new code
strictly needed), A1.3 (process isolation, needs A2/A11 first), A2
(model adapter layer), A3 (prompt library/test definitions), A4
(scoring/the judge problem — the doc's own "central design decision"),
A5 (9 benchmark categories), A6 (structured output validator), A7
(metrics collector), A8 (diagnostics), A9 (reports), A10 (the
HearthBench Score), A11 (run modes), A12 (web UI), A13 (CI prompt-
regression guard). Part B (Adaptive Runtime) — B0 (the prime invariant,
flagged "build this first" in the doc's own text — genuinely the next
natural step, not A2, since B0/B1/B2 govern how ALL scheduling works
and several already-shipped systems would need to migrate onto it) and
B1-B15 entirely (task graph, budgets/scheduling, dormancy/dirty-
tracking, cadence framework, spatial locality, etc.) beyond B15.1.
No item in either track beyond what's listed above as shipped has been
attempted. Next natural step per the doc's own sequencing: Part A's A0
(cheap, formalizes what already exists) or Part B's B0 (the doc's own
explicit "build this first" for the Runtime track) — not yet decided,
resume on future explicit direction naming one.

Verified: `node --check app.js` clean; `python3 -m pyflakes hearthbench/
scripts/verify_hearthbench_isolation.py` clean; `python3 -c "import
hearthbench"` succeeds; `scripts/verify_hearthbench_isolation.py` run
directly, confirmed clean. No native module or persisted `World` state
touched by either half of this batch — no soak re-run needed.

## Current state (v1.34.159)

Explicit user instruction: "build these next and ask question when in
doubt: districts not folded into carrying_capacity(), A19's 'battles'
axis (no combat mechanic exists), A13's reactor only reachable for
clay/fiber, §8 LoRA fine-tuning staying data-collection-only, and the
ritual/recipe grammar + Humans-vs-Village ontology split both left on
purpose," plus a request to expose more diagnostics for an overnight
real-hardware run. Resolved via `AskUserQuestion` on the first four
items (districts un-flagged already shipped separately this pass;
A19 battles -> "Full combat subsystem"; A13 -> "New BuildingKind
defaulting to ore"; §8 -> "Keep data-collection-only, extend the
tooling instead"); the ritual/recipe-vs-Humans/Village question was
explicitly delegated ("you decide this one") — my own decision,
recorded below.

**Districts folded into `carrying_capacity()`.** `Population.tick()`'s
per-settlement capacity now subtracts `sum(d.population for d in
s.districts)` before comparing against individually-simulated
population — a settlement's collectivized district population (D6,
v1.34.22) previously consumed no real headroom at all, so total real
population (individual + district) could grow unbounded even while
the individually-simulated half sat right at capacity. `carrying_
capacity`'s own tuned formula is untouched; only what districts
consume against it changed.

**A19's "battles" axis — new `world/combat.py`, a real, deterministic,
cross-settlement combat subsystem.** Deliberately scoped to
settlement-vs-settlement war, not intra-FACTION civil war (plunder
only makes sense between two separately-resourced communities).
`World._maybe_resolve_battle` (called each tick, before `Population.
tick()` so real casualties reach `_apply_deaths` the SAME tick):
checks every named-settlement pair's `Settlement.relations` against a
new `BATTLE_TRIGGER_THRESHOLD=-0.75` (deeper than the existing
diplomatic-hostility threshold, -0.5) plus a small per-tick roll
(`BATTLE_CHANCE_PER_TICK=0.0015`); a triggered pair draws real war
parties (`BATTLE_ROSTER_FRACTION=0.3` of each side's living/mature/
healthy population, floor `BATTLE_MIN_ROSTER_SIZE=2`), resolves via
`combat.resolve_battle` (winner picked probabilistically by
`roster_strength` — real headcount scaled by the party's average
`TRAIT_AMBITION`/`TRAIT_RESILIENCE`, reusing H6 psychology rather than
inventing a sixth "combat skill" axis), applies real bounded casualties
on both sides (never a wipeout — `BATTLE_CASUALTY_MAX_FRACTION=0.4`),
real plunder (`BATTLE_PLUNDER_FRACTION=0.2` of the loser's materials/
currency), real relation damage (`BATTLE_RELATION_PENALTY=0.3`), and a
new decaying `World.battle_scars` map mark at the defender's site
(`terrain_evolution.apply_battle_scar`/`decay_battle_scars`, the same
scar-dict pattern mining/disaster/road/etc. scars already established)
— the first real feed for A19's previously permanently-empty "battles"
axis. New `Population.deaths_battle` counter + `killed_in_battle`
death-cause branch in `_apply_deaths`. UI: 🗺️ battle-scar map overlay
(dark blood-red streaked mark, distinct from mining/disaster scars),
⚔️/🗡️ event icons, a "Battle scars" stat tile, and battle deaths
folded into the existing "Deaths" tile.

**A13's ore-reachable reactor — new `BuildingKind.SMELTER`.**
`world.chemistry.REACTION_RULES`' `ore + heat -> metal` rule existed
since A13 shipped but was structurally unreachable through the real
automatic reactor (`tick_building_reactions`) — no `BuildingKind` ever
defaulted to `ore` in `BUILDING_MATERIALS`, so nothing ever held ore
long enough to react. SMELTER's default material IS `ore`
(`world.materials.BUILDING_MATERIALS[SMELTER]="ore"`) and it carries
`can_conduct_heat`/`can_burn` itself (`world.affordances.
BUILDING_AFFORDANCES`, same tags as OIL_RIG/FORGE) — a furnace
supplies its own heat, so a lone standing SMELTER genuinely converts
to worked metal under sustained operation with no separate FORGE
needed. Foundable from `bronze_age` onward (`_ERA_UNLOCKS_BRONZE`,
same gate as FORGE), `SMELTER_MATERIALS_COST=4.5`. UI: map color,
"Historical infrastructure" stat tile gained a smelter count, "Built
of" inspector line reads `ore`.

**§8 LoRA fine-tuning — tooling extended, no new ML dependency
(explicit scope: no torch/peft/transformers, this environment has no
training infrastructure and none was added).** New `llm/eval_
harness.py`'s `training_readiness_report(archive_dir)`: combines FT.2's
per-task quality labels (`review_pack.label_archive`) with a volume
floor (`MIN_SFT_EXAMPLES_PER_TASK=200`, an honestly-flagged
conventional order-of-magnitude estimate, not tuned against a real
Hearthmind run) and two quality floors (`MAX_ACCEPTABLE_LEAK_RATE=
0.05`, `MAX_ACCEPTABLE_FALLBACK_RATE=0.5`) into a per-task "ready for a
first LoRA slice yet?" verdict. New `scripts/recorder_tools.py
training-readiness [--archive-dir DIR]` CLI subcommand — read-only,
prints a report, never runs or configures training.

**Ritual/recipe structure grammar — explicitly SKIPPED, not silently
dropped.** My own judgment call on the delegated decision: A7's own
prior design entry already states ritual/recipe "stays LLM-authored...
closer to meaning" — building a deterministic grammar for it would
reverse that standing decision and cuts against CLAUDE.md's own
repeated priority ("everything involving judgement, interpretation,
creativity... should default to the local LLM"). Left alone.

**Humans-vs-Village ontology origination split — built, the other half
of the same delegated decision.** New `InventedConcept.origin_pillar`
(one of `world.ontology.ONTOLOGY_ORIGIN_PILLARS = ("village", "humans",
"nature", "innovation")`, default `"village"` — legacy concepts read
correctly with zero backfill logic, since Village was the only job
that ever ran for these categories). `llm/ontology.py`'s new
`HUMANS_PROPOSE_CATEGORIES = {"custom", "saying", "profession"}` +
`origin_pillar_for_category()` implement CLAUDE.md's own standing
correction ("Humans originate customs/professions/social roles...
Village originates institutions/laws/festivals...") as real,
persisted, per-concept attribution — previously NOTHING distinguished
a Humans-flavor concept from a Village-flavor one at the data level.
`_maybe_schedule_ontology_proposal`'s apply() now computes `origin_
pillar` from the registered category and, when Humans-attributed,
mirrors a SECOND real signal into `humans_pillar.world_model` (Village/
Innovation's own existing mirrors are untouched either way — Innovation
still authors/discovers every concept through this job's machinery
regardless of who it's attributed to). `_maybe_schedule_invention`'s
technology bridge and `_maybe_schedule_nature_mind`'s ecological bridge
now pass `origin_pillar` explicitly too (`"innovation"`/`"nature"`),
closing the attribution gap for every category, not just the newly
split ones. Deliberately NOT a second parallel scheduling job (its own
budget/backpressure/gating) — a genuinely large lift beyond the actual
gap CLAUDE.md named; this is a bounded, real attribution fix. UI: the
knowledge-tree panel's lineage line now shows e.g. "(humans-
originated)" for a concept attributed to Humans.

**Diagnostics expansion for the planned overnight real-hardware run.**
`_diagnostics_snapshot()` (cheap, per-tick) gained `invented_concepts_
by_origin_pillar`, `battle_deaths_total`, `battle_scars_active_sites`,
`smelters_standing`. Deliberately did NOT add a full quality-label scan
to `/diagnostics` itself (would run `training_readiness_report`'s full
per-example scan on every poll against a potentially large overnight
archive) — that stays a separate, explicitly on-demand CLI tool.

Verified: direct unit tests (combat casualty/plunder math bounds,
`origin_pillar_for_category` over all six proposable categories,
`InventedConcept.origin_pillar` round-trip + legacy backfill,
`training_readiness_report` against a synthetic archive), production-
path tests through the real `World._maybe_resolve_battle` (forced
hostile relation, confirmed casualties/plunder/relation-damage/scar
all landed) and through the real `World.tick()`/`Population._apply_
deaths` pipeline (a genuine battle death counted, population dropped
correctly), a direct test of `tick_building_reactions` converting a
standalone SMELTER to metal end-to-end, a production-path test through
the real `_maybe_schedule_ontology_proposal` (confirmed the naturally-
fired concept's `origin_pillar` matched `origin_pillar_for_category`),
a 4000-tick LLM-disabled soak with clean round-trip, `pyflakes` clean
(only the four known pre-existing findings). No native module touched.

## Current state (v1.34.158) — Tier 3 A12 closed

Explicit user instruction: "continue tier 3 with A12 and build the
consumer by asking me," resolved via `AskUserQuestion` — "Both repair
+ decay (Recommended)." Closes A12: per-instance `Entity.material`
generalized beyond buildings (`Building.material` shipped v1.34.58) —
left unbuilt until now for lack of a real consumer, per every prior
audit's own honest note.

New `Vehicle.material: str | None = None` (settlement/vehicles.py,
same "`None` = use the kind's default, zero migration" shape as
`Building.material`) and `world/materials.py`'s `VEHICLE_MATERIALS`
(CART/RAFT/BOAT -> wood, AUTOMOBILE -> metal, MOUNT -> fiber —
deliberately assigned, since the vehicle abstraction represents a
mount's tack/stabling, not the living animal) + `effective_vehicle_
material_name`, the exact per-instance-resolution counterpart to
`effective_material_name`. Both real consumers buildings already have
generalize for free — `material_repair_factor`/`material_decay_
factor` were already pure functions of a material NAME, never
Building-specific, so no new formula was needed: `Population._maybe_
repair_vehicles` now scales repair speed by the vehicle's own material
workability, and every wear site (`_wear_carts`, `_wear_rafts`, and
all three `PERSONAL_VEHICLE_USE_DECAY` mount/automobile decay sites)
now scales by the vehicle's own material decay_rate — a metal
automobile now wears down markedly slower than a wood cart, a stone-
hulled boat repairs markedly slower than a fiber-tacked mount, the
same real-world intuition A5/A6 already made mechanical for buildings.
Pure Python throughout (`Settlement.vehicles`' condition/repair/wear
math has no native fast path, unlike buildings' `_native_building_
decay_tick`) — zero native-parity risk, no native-module change
needed.

No per-instance vehicle click-inspector exists in the UI at all yet
(vehicles only ever reach `/state` as an aggregate "Vehicles" stat
tile) — flagged honestly rather than building a whole new inspector
UI as unrequested scope; the mechanic is real and verified regardless
of whether it's yet visible per-instance in the browser.

Verified: direct tests for default per-kind material resolution
(CART/AUTOMOBILE/MOUNT), explicit-override resolution, `to_dict`/
`from_dict` round-trip (incl. a legacy snapshot with no `material` key
at all defaulting to `None`), a production-path test through the real
`_maybe_repair_vehicles` confirming a fiber cart genuinely repairs
faster than a stone cart, production-path tests through the real
`_wear_carts`/`_wear_rafts` confirming a fiber vehicle wears
measurably faster than a stone one, a direct check confirming an
unrecognized/absent material still reproduces the exact old flat 1.0x
behavior; a 4000-tick LLM-disabled soak with clean round-trip;
`pyflakes` clean (only the four known pre-existing findings remain).

**Tier 3 is now fully closed** — A12 was its last open item.

## Current state (v1.34.157) — Tier 3 C2 closed

Explicit user instruction: "continue tier 3 c2 with the next intention"
— C2's eighth and final slice, "build," resolved without a fresh
`AskUserQuestion` (only one intention remained, no choice to make).
**This closes C2** — all eight named pillar-emitted intentions are now
shipped. Named as the largest structural bypass in the whole channel:
`_maybe_start_construction`'s ordinary path only ever fires when two
founders happen to colocate on the same tile; `Population._maybe_
civic_construction` genuinely INITIATES a real construction attempt
with NO colocation required at all, driven purely by `village_pillar`'s
own standing conviction that the settlement is prosperous.

Reuses the existing `"prosperity"` category-keyed producer (`_detect_
prosperity`, v1.34.142) rather than inventing a new signal — the one
positive-framed subject in the whole village_pillar vocabulary was
already exactly right for "invest in a civic project." New `VILLAGE_
CIVIC_BUILD_CONVICTION_THRESHOLD=0.9` (buildings.py) — deliberately
0.05 above every sibling C2 threshold, the highest bar in the channel,
since this spends real settlement materials with no founders having
chosen to build there themselves. Computed once per tick in `World.
tick()`, gated to a weekly cadence (checked far less often than a
per-tick gate, matching the size of the bypass). Body still gates the
real outcome: a settlement already mid-project (any `UNDER_
CONSTRUCTION` building) is skipped outright — never stacks a second
project on an ongoing one, organic or civic — and needs at least two
real living, mature, healthy members to found it, the same eligibility
bar as the ordinary colocation path. Reuses `_choose_build_site`/
`choose_building_kind` unchanged, anchored at one of the settlement's
own standing buildings (there being no colocated group position to
anchor from) rather than a founders' shared tile. New `civic_
construction_started` event category (🏛️). Closes the loop: a genuine
civic construction reinforces `"prosperity"` to full confidence in
place, same shape every other C2 confirmation uses.

Verified: a production-path test confirming a genuine civic
construction fires (materials spent, a real `UNDER_CONSTRUCTION`
building appears) with no colocated founders present at all; a
negative case for `civic_build_convicted=False`; a negative case for a
settlement already mid-project; a negative case for insufficient
materials; a regression case for an unnamed/unfounded settlement never
crashing; a full production-path test driving the real clock to a
genuine `week_end` tick and calling `Population.tick()` through the
exact same signature `World.tick()` uses, confirming a real civic
construction fires end to end; a 4000-tick LLM-disabled soak with
clean round-trip; `pyflakes` clean (only the four known pre-existing
findings remain). No native module touched.

**C2 is now fully shipped**: invent tech, change law, propose
experiment, shift land use, set custom, reorganize institution,
domesticate, build — all eight named pillar-emitted intentions from
`docs/MASTERCHECKLIST-2026-07-22.md`'s Part C are real, verified,
production-quality slices.

## Current state (v1.34.156)

Explicit user instruction: "continue tier 3 c2 with the next intention,"
resolved via `AskUserQuestion` — "Domesticate (Recommended)." C2's
seventh slice, and the one genuinely NEW mechanism among all eight
named intentions: no wild-herd-to-tame-stock conversion existed
anywhere in this codebase before this slice (every other C2 slice
reused an existing mirror/action).

Village pillar's sixteenth category-keyed `world_model` subject,
`"grazer_abundance"`: `_detect_grazer_abundance` (daily-metrics
cadence, edge-triggered, alongside `_detect_guild_decline`) mirrors
whenever a settlement has a standing PASTURE with a real wild GRAZER
herd within `WILDLIFE_SEARCH_RADIUS` holding at least `DOMESTICATE_
MIN_HERD_SIZE` animals — Body supplies the real precondition. Once
`village_pillar` holds strong conviction about it (`VILLAGE_
DOMESTICATE_CONVICTION_THRESHOLD=0.85`), `_maybe_domesticate_grazers`
genuinely captures wild animals into the pasture's own `stored_food`
via `WildlifeGrid.hunt` — the same native-index-safe removal primitive
a predator kill already uses, zero added native-parity risk.

Deliberately decoupled the ONGOING action from the mirror's own
higher "genuinely abundant" gate (`DOMESTICATE_MIN_HERD_SIZE=4`): once
conviction is already strong, `_maybe_domesticate_grazers` acts
against any real nearby herd down to `DOMESTICATE_HERD_FLOOR=2` (never
below — domestication skims a genuine surplus, it never risks
extirpating the wild population), rather than stalling the instant one
capture drops the herd back below the abundance bar. Bounded by
`DOMESTICATE_CAPTURE_SIZE=1` per firing and PASTURE headroom
(`PASTURE_CAPACITY`) each time, so this reads as a slow, repeated
absorption over many days, not a single sweep. New `grazers_
domesticated` event category (🐑).

Verified: a production-path test confirming a genuine capture fires
(pasture stock rises, herd shrinks, mirror reinforced to confidence
1.0 in place); a negative case for conviction below threshold; a
negative case confirming a fresh sighting with zero prior pillar
content only ever mirrors (0.3 -> 0.4) without capturing, since 0.4 is
far below the acting threshold; a negative case for a herd already at
the floor; a repeated-call test confirming the floor is genuinely
reached and then respected (4 -> 3 -> 2 -> stays 2); a negative case
for a full pasture; a regression case confirming no PASTURE at all
never crashes; a 4000-tick LLM-disabled soak with clean round-trip;
`pyflakes` clean (only the four known pre-existing findings remain).
No native module touched.

C2 now has seven of eight named intentions shipped (invent tech,
change law, propose experiment, shift land use, set custom, reorganize
institution, domesticate). One remains open: "build" — genuinely
INITIATING a construction attempt outside `_maybe_start_construction`'s
existing colocation-triggered roll, distinct from "shift land use"
(v1.34.153), which only overrides WHAT gets built at a site Body has
already decided to start — "build" would change WHETHER one starts at
all. Still flagged, not attempted this pass; needs its own design
decision naming a real trigger Mind could initiate from (e.g. a
civic-project conviction independent of the ordinary colocation roll).

## Current state (v1.34.155)

Explicit user instruction: "continue tier 3 c2 with the next intention"
— C2's sixth slice, "reorganize institution." No dissolution mechanism
exists anywhere in this codebase (institutions persist until pruned
only by `INSTITUTION_LIST_MAX_STORED`), so a genuine "reorganize"
needed a shape that doesn't require inventing one: `_detect_guild_
decline`'s own existing per-tick check (a GUILD with no living member
still holding `GUILD_SKILL_MASTERY_THRESHOLD` in its own named skill)
now, once `village_pillar` holds strong conviction about that SPECIFIC
guild's name, RENAMES it in place to a different skill one of its own
living members has actually mastered — restructuring around a new
purpose while preserving membership/beliefs/history, rather than
dissolving and re-founding. `Institution.name` for a GUILD literally
IS the skill, and guild-membership-by-skill is rebuilt fresh every
tick from `.name` with no caching, so the rename carries zero
dangling-reference risk.

New `VILLAGE_INSTITUTION_REORGANIZE_CONVICTION_THRESHOLD=0.85`
(engine.py, same bar as every other override-class C2 slice). The
conviction read (`village_pillar.subject_confidence(guild.name)`)
deliberately fuzzy-matches `_maybe_schedule_guild_founding`'s existing
`"the {skill} guild"` mirror — the guild's own founding belief — so a
guild the village has held lasting conviction about since it was
founded is the one that gets a real second chance. Body stays
authoritative throughout: the guild must already be genuinely
declining this same tick, the candidate skill must not already be
claimed by another guild in the settlement, and at least one of the
declining guild's own LIVING members must already hold real mastery in
it — conviction alone, with no real alternate-skill master among the
guild's own membership, can never manufacture a reorganization (a
declining guild with no qualifying alternate simply stays declining,
same as before this slice). New `_maybe_reorganize_guild` helper,
called from `_detect_guild_decline`'s existing per-guild loop; a
successful reorganization means that guild no longer counts as
declining this tick (skips `pattern_signal_counts["guild_decline"]`'s
increment for it), closing the loop by reinforcing the guild-founding
mirror entry (keyed by the OLD skill name) to full confidence in
place. New `institution_reorganized` event category (🔁).

Verified: a production-path test confirming a genuine reorganization
fires (rename, event, mirror reinforced to confidence 1.0 in place, no
longer counted as declining); a negative case for conviction below
threshold; a negative case for no qualifying alternate-skill master
among the guild's own living members; a positive case confirming a
skill already claimed by another guild in the settlement is correctly
skipped in favor of the next eligible one; a regression test
confirming ordinary `guild_decline` detection/`pattern_signal_counts`/
mirror behavior is unchanged when no reorganization is possible; a
4000-tick LLM-disabled soak with clean round-trip; `pyflakes` clean
(only the four known pre-existing findings remain). No native module
touched.

C2 now has six of eight named intentions shipped (invent tech, change
law, propose experiment, shift land use, set custom, reorganize
institution). Two remain open: domesticate (no existing mechanism at
all — the largest remaining lift), build (currently baked into a
continuous per-tick colocation-triggered roll in `_maybe_start_
construction`, the same function "shift land use" already touches —
a future slice needs to think carefully about how it differs from
that existing WHAT-override).

## Current state (v1.34.154)

Explicit user instruction: "continue tier 3 c2 with the next intention"
— C2's fifth slice, "set custom," resolved without a fresh
`AskUserQuestion` (a prior turn's question on this exact choice went
unanswered/interrupted; "set custom" was already the flagged
recommended default with a concrete design). `village_pillar`'s own
persisted conviction about one of `laws.py`'s hardship subjects can
now genuinely FORCE `_maybe_schedule_ontology_proposal`'s category to
`"custom"` — overriding whatever the LLM itself would freely pick
among `VILLAGE_PROPOSE_CATEGORIES`'s six options — when the job's
existing Body-driven pressure check found nothing fresh to name this
cycle. Reuses `_LAW_PATTERN_TEXT`'s closed vocabulary directly rather
than inventing a second one: a custom is the informal, not-yet-
codified sibling of a law about the same lived hardship.

New `VILLAGE_CUSTOM_CONVICTION_THRESHOLD=0.85` (engine.py, same bar as
`VILLAGE_LAND_USE_CONVICTION_THRESHOLD`/`REFLECTION_PILLAR_CONVICTION_
EXPERIMENT_THRESHOLD` — every C2 slice that overrides an already-
decided outcome holds to this stricter bar than the two that only
initiate a call). Deliberately scoped narrower than "shift land use":
only ever fills a MISSING `pressure_signal` (the job's real Body-
driven occurrence count, when it crosses `PATTERN_SIGNAL_BELIEF_
THRESHOLD`, is never overridden — verified directly with an unrelated
strong conviction present at the same time). The category override
itself happens in `apply()`, after the LLM responds, not merely as a
prompt hint — genuinely forces `parsed["category"] = "custom"`
regardless of what the model said. Closes the loop the same way every
other C2 slice does: a real custom that registers from a conviction-
initiated override reinforces the driving hardship subject to full
confidence in place.

Verified: a production-path test confirming a prosperous-but-not-
fresh-pressured settlement still grounds the prompt from conviction
alone and the registered concept's category is forced to "custom"
regardless of the LLM's own claimed category; a production-path test
confirming a below-threshold conviction leaves the category untouched;
a regression test confirming a real fresh occurrence-driven pressure
signal is never overridden by an unrelated strong conviction; the
conviction-confirmation reinforcement verified to revise in place (no
duplicate); a 4000-tick LLM-disabled soak with clean round-trip;
`pyflakes` clean (only the four known pre-existing findings remain).
No native module touched.

C2 now has five of eight named intentions shipped (invent tech, change
law, propose experiment, shift land use, set custom). Three remain
open: reorganize institution, domesticate, build — each still needing
its own design decision per the v1.34.151 audit.

(Superseded by v1.34.155 above: reorganize institution has since
shipped.)

## Current state (v1.34.153)

Explicit user instruction: "continue tier 3 c2 with the next intention,"
resolved via `AskUserQuestion` — "Shift land use." C2's fourth slice
and the strongest form of intervention any C2 site has used so far:
`village_pillar`'s own standing conviction about a real, already-
tracked shortage (`food_shortage`/`housing_shortage`/`currency_
shortage`) can now genuinely FORCE the settlement's next construction
site to a specific kind — overriding `choose_building_kind`'s own
weighted roll outright, not merely initiating a call that wouldn't
otherwise happen (invention/laws/self_tuning) or leaning its odds
(every Tier 0 site). This changes WHAT gets built at an already-
decided site, the literal "shift land use."

New `buildings.VILLAGE_LAND_USE_CONVICTION_THRESHOLD=0.85` (the
highest bar of the four C2 slices, since overriding an already-decided
outcome is a stronger intervention than initiating one) and `LAND_USE_
SHIFT_TARGET_KIND` (a closed subject->kind map: food_shortage->
PASTURE, housing_shortage->HUT, currency_shortage->WORKSHOP — all
three deliberately UNGATED kinds in `choose_building_kind`, so an
override can never produce an invalid building regardless of era/
tradition/caravan/water-adjacency state). Computed once per tick in
`World.tick()` (same "compute once over a small fixed set" discipline
as `building_kind_pillar_lean`/`occupation_pillar_lean`), threaded
through `Population.tick()` into `_maybe_start_construction`'s
existing `kind = choose_building_kind(...)` call site. Deliberately
bounded against runaway conversion: the override only applies while
the settlement doesn't already have a standing/under-construction
building of the target kind — a genuine one-time strategic
reallocation of the next parcel of land, not a permanent override that
would starve every other building kind while conviction stays high.

Closes the loop the same way every other C2 slice does: once the
override genuinely produces a real "construction_started" event
naming the target kind (parsed off the same stable description
template `_village_priority_lean`'s kind-momentum mirror already
reuses), the driving shortage subject's own `village_pillar` entry is
reinforced to full confidence in place.

Verified: a direct unit test through the real `_maybe_start_construction`
classmethod confirming the override fires, confirming it's a genuine
one-time reallocation (no-op once the settlement already has the
target kind, falling back to normal weighted choice), and a no-override
regression case; a full production-path integration test through the
real `World.tick()` (seeded conviction, real colocated founders, real
materials/site-selection/settle-chance path) confirming a genuine
PASTURE construction fires and the food_shortage conviction is
reinforced to full confidence in place with no duplicate entry; two
threshold-boundary checks (below-threshold conviction, zero conviction
anywhere) both correctly yielding no override; a 4000-tick LLM-
disabled soak with clean round-trip; `pyflakes` clean across all four
touched files (only the four known pre-existing findings remain). No
native module touched.

C2 now has four of eight named intentions shipped (invent tech, change
law, propose experiment, shift land use). Four remain open: set
custom, reorganize institution, domesticate, build — each still
needing its own design decision per the v1.34.151 audit.

## Current state (v1.34.152)

Explicit user instruction: "fix the previous found flaws first,"
resolved via `AskUserQuestion` to "re-audit my last 3 C2 commits"
(v1.34.149-.151). Found one real, load-bearing bug — fixed, no new
mechanism.

**Bug**: `llm/self_tuning.py`'s `build_prompt` unconditionally told the
model "Your **supported** hypothesis about it: {text}" — accurate for
the original path (a hypothesis that survived `_reevaluate_reflection_
hypotheses`'s multi-cycle evidence loop to reach `status="supported"`),
but v1.34.151's own conviction-initiated path deliberately tests a
still-`"open"` hypothesis *because* it hasn't reached that status yet.
The prompt was silently lying to the model about the hypothesis's real
epistemic status on every conviction-initiated firing — directly
undermining the feature's own stated "evidence stays authoritative"
principle, since the model was never told the evidence wasn't actually
settled. Fixed: `build_prompt` gained a `via_conviction` param, wired
from `_maybe_schedule_self_tuning`'s real `initiated_by_conviction`
flag — the conviction path now honestly reads "A hunch you feel
strongly about, though the evidence hasn't fully settled it yet."

**Secondary gap, same audit**: `llm/laws.py`'s `build_prompt` passes
the raw `occurrences` count with no framing — legitimately as low as 1
on a conviction-initiated firing (v1.34.150), which against `SYSTEM_
PROMPT`'s own "most of the time it is NOT yet settled" default risked
the feature being practically inert (the model told "occurred 1 time"
would almost always answer "not yet," regardless of the real standing
conviction driving the call). Fixed with a `remembered` param — a
conviction-initiated prompt now honestly notes "this is far from the
village's first brush with it; the memory of it has lingered ever
since," giving the model the real context missing from the bare count.

Both fixes are prompt-content-only — no scheduling/gating/confirmation
logic changed; every test from v1.34.149-.151 re-run and still passes
unmodified. Verified: direct assertions on both new prompt branches
(conviction wording present/absent as expected); full production-path
regression re-run for all three C2 slices (invention hypothesis-
resolution, laws conviction-confirmation, reflection experiment-
confirmation) unmodified and still passing; a 4000-tick LLM-disabled
soak with clean round-trip; `pyflakes` clean (same four pre-existing
findings only). No native module touched.

## Current state (v1.34.151)

Explicit user instruction: "continue tier 3 c2 with the next intention
do as many this turn as possible" — C2's third slice, "propose
experiment." `reflection_pillar`'s own persisted confidence in a
still-OPEN hypothesis (not yet promoted to `status="supported"`
through the normal slow, multi-cycle `_reevaluate_reflection_
hypotheses` evidence loop) can now genuinely INITIATE testing it early
via the sandboxed self-tuning path (item 1.3's "test the hypothesis in
a jar") — `_maybe_schedule_self_tuning` no longer requires a hypothesis
to reach `REFLECTION_SUPPORTED_THRESHOLD` before a genuinely convinced
Reflection can act on it.

New `REFLECTION_PILLAR_CONVICTION_EXPERIMENT_THRESHOLD=0.8` (engine.py,
alongside `REFLECTION_SUPPORTED_THRESHOLD`/`REFLECTION_REJECTED_
THRESHOLD`) — deliberately stricter than `VILLAGE_PATTERN_CONVICTION_
LAW_THRESHOLD`'s 0.75, since this bypasses the Body-authoritative
promotion process entirely rather than just re-opening a reset
counter. `reflection_pillar.world_model`'s mirrored confidence (a
one-time snapshot taken at proposal time, never re-synced with the
notebook's own evolving `confidence`) is the genuinely distinct
signal driving this — "Reflection's persisted conviction was already
strong, independent of how fresh evidence has drifted since." Evidence
still stays authoritative: an open hypothesis whose OWN notebook
confidence has already dropped to/below `REFLECTION_REJECTED_
THRESHOLD` can never be force-tested purely on stale initial
conviction. Scoped to the governor-mapped path only (not the advisory
path, which has no sandboxed confirmation to close a loop against).
Closes the loop symmetrically with invention/laws: a real sandbox-
validated adjustment that followed from a conviction-initiated attempt
reinforces that pillar entry to full confidence in place.

Verified: a production-path test confirming the conviction path fires
on an OPEN (not "supported") hypothesis when pillar confidence
qualifies; a production-path test through the real `apply()` closure
(including awaiting the real sandboxed `_validate_and_tune` background
task) confirming the seeding conviction entry is reinforced to
confidence 1.0 in place; a negative case for low pillar confidence; a
negative case for a hypothesis whose own notebook confidence already
trends toward rejection (Body-authority regression guard); a negative
case for a subject with no governor mapping at all (conviction alone
can't manufacture a target); a regression test confirming the ordinary
`status="supported"` path fires completely unchanged; a 4000-tick
LLM-disabled soak with clean round-trip; `pyflakes` clean (only the
four known pre-existing findings remain). No native module touched.

C2 now has three of eight named intentions shipped (invent tech,
change law, propose experiment). Five remain open: set custom,
reorganize institution, shift land use, domesticate, build. A fourth
slice was not attempted this turn after a deliberate audit of the
remaining five found no equally clean fit: "build" is baked into a
continuous per-tick physical mechanic (`_maybe_start_construction`'s
colocation-triggered roll) rather than a discrete gated cognition job,
"domesticate" has no existing mechanism to extend at all (a genuine
new-mechanism build, not a slice), and "set custom"/"reorganize
institution"/"shift land use" each map onto jobs (`_maybe_schedule_
ontology_proposal`, `_maybe_schedule_rule_proposal`, `_maybe_schedule_
institution_belief`) that already fire unconditionally every cycle —
none has a real WHETHER-gate left to bypass, so a genuine C2 slice
there needs its own design decision, not a mechanical repeat of this
turn's pattern.

## Current state (v1.34.150)

Explicit user instruction: "continue tier 3 c2 with the next intention"
— C2's second slice, "change law." `village_pillar`'s own standing
conviction about a hardship category can now genuinely INITIATE a law
proposal ahead of fresh occurrences re-crossing `LAW_SIGNAL_THRESHOLD`
— not merely a tiebreak among already-qualifying candidates (that's
what Tier 0's 25th site already did). New `buildings.VILLAGE_PATTERN_
CONVICTION_LAW_THRESHOLD=0.75`: when no candidate's raw occurrence
count clears the normal threshold, `_maybe_schedule_laws` now checks
whether ANY category with at least one real recent occurrence (Body
stays authoritative — conviction alone with zero fresh evidence never
initiates anything, verified directly) has village_pillar confidence
at or above this bar; if so, that category's own mirror entry becomes
the real initiating signal, not a fallback.

This captures something Tier 0's lean never could: `village_pillar`'s
confidence about a category persists from BEFORE a prior law's
enactment reset the raw occurrence counter (see apply()'s existing
reset), so a settlement that already legislated once can act again on
its own unresolved memory well before fresh hardship alone would
re-qualify — "the village hasn't forgotten," not just "the village
is currently suffering." Closes the loop symmetrically with the
invention slice: once a real law is enacted from a conviction-
initiated attempt, that pillar entry is reinforced to full confidence
in place (`revises_id`), not duplicated.

Verified: a production-path test confirming the conviction path fires
below the occurrence threshold when confidence qualifies; a
production-path test through the real `apply()` closure confirming
the seeding conviction entry is reinforced to confidence 1.0 in place
(no duplicate) and the occurrence counter still resets normally on
enactment; a negative-case test for confidence below threshold; a
second negative-case test confirming conviction with literally zero
real recent occurrences never initiates anything (Body-authority
regression guard); a regression test confirming the ordinary Body-
threshold-driven path fires completely unchanged; a 4000-tick LLM-
disabled soak with clean round-trip; `pyflakes` clean on both touched
files (no new findings beyond the four pre-existing, already-confirmed
harmless hits). No native module touched.

C2 now has two of eight named intentions shipped (invent tech, change
law). Six remain open: set custom, reorganize institution, shift land
use, domesticate, build, propose experiment.

## Current state (v1.34.149)

Explicit user instruction: "start c2", resolved via `AskUserQuestion` —
"Innovation-initiated invention (Recommended)." First real C2
("Intention channel," Mind -> Body, `docs/MASTERCHECKLIST-2026-07-
22.md`'s Part C) slice: `innovation_pillar`'s own leading OPEN
(`status="hypothesis"`) `world_model` belief now genuinely INITIATES
an invention attempt, not merely biases an existing one. This is
architecturally distinct from every Tier 0 site, which only ever broke
a tie or nudged an outcome that was going to happen anyway — this
changes WHETHER the event happens at all.

New `buildings.INNOVATION_HYPOTHESIS_CONFIDENCE_THRESHOLD=0.6` (the
bar a hunch must clear to count as genuinely converged-on, not every
half-formed idea) and `INNOVATION_HYPOTHESIS_INVENTION_BONUS_WEIGHT=
0.5` (max chance multiplier, scaled by the hunch's own confidence).
`_maybe_schedule_invention` looks up Innovation's highest-confidence
open hypothesis and, once it clears the threshold, boosts `chance`
strictly AFTER the existing prosperity gate — a pillar's conviction
makes a breakthrough come more readily once the village can actually
afford one, never in place of real surplus (Body stays authoritative,
per `docs/CONSTITUTION.md`'s priority order). `llm/invention.py`'s
`build_prompt` gained an optional `hunch` param grounding the actual
LLM call in Innovation's own stated hunch text. The loop closes in
apply(): once a real invention forms from a hypothesis-seeded attempt,
that hypothesis is revised in place (`upsert_world_model` with
`revises_id`) to `status="observation"`, confidence 1.0, its belief
text appended with "This hunch led to a real invention: {name}." —
hypothesis -> action -> confirmation, not left to fade unresolved.

Verified: a direct production-path test confirming the boost genuinely
flips whether the job schedules at all (same roll value fires only
with a confident hunch present, not without one) — the load-bearing
proof this is a real intention, not a tiebreak; a positive-case
production-path test through the real `apply()` closure confirming the
seeding hypothesis is revised in place (not duplicated) once the
invention forms; a negative-case test confirming a hypothesis below
the confidence threshold is left untouched; a 4000-tick LLM-disabled
soak with clean `to_dict()`/`from_dict()` round-trip; `pyflakes` clean
across all three touched files (`settlement/buildings.py`, `llm/
invention.py`, `simulation/engine.py`) — no new findings beyond the
four pre-existing `undefined name 'Agent'/'Building'/'Institution'`
hits already confirmed harmless in prior passes this session. No
native module touched.

C2 names eight pillar-emitted intentions total (invent tech, set
custom, change law, reorganize institution, shift land use,
domesticate, build, propose experiment) — this ships only the first
("invent tech"). The other seven remain open, not attempted; resume
only on future explicit direction.

## Current state (v1.34.148) — Tier 0 closed

Explicit user instruction: "continue tier 0 and finish it this turn
so that we can move to new tier." No further real site found this
pass (a fresh sweep of `llm/*.py`/`world/*.py`/`settlement/*.py`/
`agents/population.py` after last turn's `faction_rivalry` site
turned up nothing new) — this turn is docs-only, closing the tier
rather than adding another site.

**What "closed" means here, precisely.** Tier 0's own original 149-
step checklist (docs/ROADMAP-2026-07-REMAINING.md's standalone
checklist) was already fully done before this session. What this
session added (v1.34.137-.147, nine new category-keyed producers —
`food_shortage`/`prosperity`/`currency_shortage`/`council_gridlock`/
`guild_decline`/`family_extinction`/`diplomatic_hostility`/`faction_
rivalry`, plus two pure-consumer conversions of already-existing
signals — is real work, but it's from an open-ended extension of the
pattern (mirror-write -> pillar-authored decisions, then new pattern-
signal categories) that by its own nature never reaches a fixed
"done": every session that looked for one more real site this
extension supports found one, this one included (nine, the most of
any single session). There is no principled stopping point inside
that pattern itself — only a decision to stop looking for now.

That decision is what actually happened this turn: Tier 0 is
reclassified from a gating tier (blocking movement to other tiers)
to ongoing opportunistic maintenance, same standing as Tier 4's
never-finished discipline items — pick a new site up again whenever
one is genuinely found, but it no longer blocks work elsewhere.
docs/ROADMAP-2026-07-REMAINING.md's own Tier 0 narrative section
(which had stopped being updated turn-by-turn around the v1.34.46-
era "~52 remaining" note, with CLAUDE.md as the real log since) gets
one closing summary appended recording this accounting rather than
a full backfill of every intermediate entry — redundant with this
file's own history above.

**Final tally**: 14 real `_maybe_schedule_laws` hardship categories
(theft, dispute_feud, materials_bottleneck, housing_shortage, food_
shortage, disease_outbreak, currency_shortage, starvation_death,
wildlife_recolonization, council_gridlock, guild_decline, family_
extinction, diplomatic_hostility, faction_rivalry) plus one positive-
signal producer (`prosperity`, deliberately routed to `_maybe_
schedule_festival` instead of the hardship-framed laws prompt) — every
one of the four institution kinds (COUNCIL/GUILD/FAMILY/FACTION) has
a real signal, spanning economy/health/housing/ecology/governance/
diplomacy. ~30 tiebreak-lean conversions across town_brain, era_
branch, guild founder, fission leader, council seats, dispute
pairing, migration candidates, voice-pair selection, inheritance
heirs, and more, from earlier in Tier 0's history.

**Handoff to the next tier.** Tier 1/1.5/2 are already fully closed
per the roadmap doc. Tier 3 has exactly two named open items left:
**C2** ("most spec-named pillar-emitted intentions aren't pillar-
emitted at all... mostly waits on Tier 0" — flagged genuinely large,
not attempted) and **A12** (per-instance `Entity.material` beyond
buildings — correctly left unbuilt, no real consumer exists for e.g.
a Vehicle's material yet). Tier 4 is standing discipline by design
(never "finished"). Tier 5 (HearthBench & the Adaptive Runtime) has
only its first item shipped (`scripts/verify_replay_hash.py`,
v1.34.102) out of a 30+-item two-track checklist. C2 is the most
natural next body of work — it's the one item that named Tier 0's
own completion as its blocker, and that blocker is now cleared.

## Current state (v1.34.147)

Explicit user decision via `AskUserQuestion`: "Design a FACTION
rivalry signal" — this session's first genuinely-new-mechanism
producer rather than a rewiring of already-existing state. Village
pillar's fifteenth category-keyed `world_model` producer, a fourth
institution-scoped one alongside `council_gridlock`/`guild_decline`/
`family_extinction`. New `agents/population.py` constants `FACTION_
RIVALRY_THRESHOLD` (-0.3, shallower than `DISPUTE_RELATIONSHIP_
THRESHOLD`'s -0.6 since an averaged multi-pair reading regresses
toward zero far more than one festering pair) and `FACTION_RIVALRY_
MIN_MEMBERS` (2, so a comparison never reduces to just one person's
opinion — already covered by ordinary dispute detection). New
`SimulationEngine._detect_faction_rivalry` (daily-metrics cadence,
edge-triggered): two FACTION institutions in the same settlement,
each with enough living members, whose average cross-membership
`Agent.relationships` reading (both directions) drops below
threshold.

New real consumer: `_maybe_schedule_laws`'s `candidates` dict gains a
genuine FOURTEENTH option — sustained factional strife can now
produce a real reconciliation law.

Verified: a direct production-path test confirming neutral
relationships never flag, a genuine cross-faction hostility forms/
flags the entry, recovery clears it, and factions below the min-
member floor never flag even at maximum hostility; a production-path
test for the consumer through the real `_maybe_schedule_laws`; a
4000-tick LLM-disabled soak with clean round-trip, `pyflakes` clean.
No native module touched. Tier 0 now has fifty-one real converted
sites.

## Current state (v1.34.146)

Explicit user instruction: "Continue tier 0." Village pillar's
fourteenth category-keyed `world_model` producer, back to the level-
based/recoverable shape (`prosperity`/`currency_shortage`) rather than
the one-shot `family_extinction` — and the first to reuse already-real
`Settlement.relations` cross-settlement affinity state, no new tracked
data. New `SimulationEngine._detect_diplomatic_hostility` (daily-
metrics cadence, edge-triggered): any recorded relation with a sister
settlement drops below new `buildings.DIPLOMATIC_HOSTILITY_THRESHOLD`
(-0.5, deliberately deeper than `llm/diplomacy.py`'s own "cold"
narration tone of -0.3, since this backs a real hardship signal, not
just prompt wording). Only ever fires in a multi-settlement world — an
empty `relations` dict never crosses the threshold, verified directly.

New real consumer: `_maybe_schedule_laws`'s `candidates` dict gains a
genuine THIRTEENTH option — sustained hostility with a neighbor can
now produce a real border-defense/militia law.

Verified: a direct production-path test for the producer (forms on a
forced-hostile relation, clears on recovery, never flags an empty
relations dict), a production-path test for the consumer through the
real `_maybe_schedule_laws`, a 4000-tick LLM-disabled soak with clean
round-trip, `pyflakes` clean. No native module touched. Tier 0 now has
fifty real converted sites.

## Current state (v1.34.145)

Explicit user instruction: "Continue tier 0" — followed my own
closing note from last pass ("FAMILY institutions are the one
remaining un-mined category"): "FAMILY-level signal."

Village pillar's thirteenth category-keyed `world_model` producer, a
third institution-scoped one. Unlike `council_gridlock`/`guild_
decline` (level-based, can recover), a family line dying out is a
genuine one-shot event — new `SimulationEngine._detect_family_
extinction` fires once a FAMILY institution that once had real
membership has no living member left. `_family_extinction_counted`
tracks which FAMILY ids were already counted so the same line's death
is never double-counted; intersected against every currently-present
FAMILY id on each check so an evicted family's id drops out rather
than lingering forever — bounded by the same `INSTITUTION_LIST_MAX_
STORED` cap `Settlement.institutions` itself already holds, not a new
unbounded structure.

New real consumer: `_maybe_schedule_laws`'s `candidates` dict gains a
genuine TWELFTH option — a settlement that keeps watching family
lines vanish can now produce a real inheritance/succession law.

Verified: a production-path test confirming no count while the family
is alive, a real count once the line dies out, no double-count on a
second check, and the id genuinely dropping out of the tracked set
once the family is evicted from `settlement.institutions`; a
production-path test for the consumer through the real `_maybe_
schedule_laws`; a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean. No native module touched. Tier 0 now has forty-nine
real converted sites.

## Current state (v1.34.144)

Explicit user instruction: "Continue tier 0," resolved via
`AskUserQuestion` after a subject_confidence()-vs-producer cross-
check found no new dead-consumer bugs: "GUILD-level signal."

Village pillar's twelfth category-keyed `world_model` producer, a
second institution-scoped one alongside `council_gridlock`. New
`SimulationEngine._detect_guild_decline` (daily-metrics cadence,
edge-triggered): a GUILD's `Institution.name` IS the exact skill it
formed around — fires once no living member still holds `GUILD_
SKILL_MASTERY_THRESHOLD` in that skill, i.e. the craft has genuinely
died out among the guild's own membership. A freshly-founded guild
can never trivially trigger this (formation itself requires real
living masters); verified directly. Settlement-scoped, not per-guild
— a settlement with multiple guilds flags if any one of them has
declined.

New real consumer: `_maybe_schedule_laws`'s `candidates` dict gains a
genuine ELEVENTH option — a dying craft can now produce a real
apprenticeship/guild-support law, same shape every prior category-
keyed producer established.

Verified: a production-path test confirming the flag never fires
right at founding, fires once every member's skill genuinely drops
below mastery, and clears once one member re-masters it; a
production-path test for the consumer through the real `_maybe_
schedule_laws`; a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean. No native module touched. Tier 0 now has forty-
eight real converted sites.

## Current state (v1.34.143)

Explicit user instruction: "Continue tier 0," resolved via
`AskUserQuestion` after a codebase-wide re-scan (population.py,
llm/*.py, world/*.py, settlement/*.py) found no further real-signal-
plus-arbitrary-tiebreak sites: "COUNCIL gridlock producer."

Village pillar's eleventh category-keyed `world_model` producer, and
the first institution-scoped one in this cluster. New `SimulationEngine._detect_council_gridlock`
(daily-metrics cadence, edge-triggered): a settlement's COUNCIL has
living members drawn from more than one real `FACTION`, yet
`Population.council_faction_majority` still reads `None` (no faction
commands a strict majority) — a genuinely split, politically-
contested council. Deliberately distinguished from an apolitical
council (no faction membership at all, which also reads `None` from
`council_faction_majority` but isn't gridlock) by checking real
faction presence directly rather than trusting `None` alone —
verified via a direct test that a councilless-of-factions settlement
never gets flagged.

New real consumer: `_maybe_schedule_laws`'s `candidates` dict gains a
genuine TENTH option — a council that keeps failing to agree can now
produce a real reform/succession-rule law, same shape every prior
category-keyed producer established.

Verified: a production-path test for the producer (a genuine 3v3
council split forms/flags; giving one faction a 4v2 majority clears
the flag; removing both factions — an apolitical council — never
flags at all), a production-path test for the consumer through the
real `_maybe_schedule_laws`, a 4000-tick LLM-disabled soak with clean
round-trip, `pyflakes` clean. No native module touched. Tier 0 now
has forty-seven real converted sites.

## Current state (v1.34.142)

Explicit user instruction: "Continue tier 0 ask is needed new
system," resolved via `AskUserQuestion` — "Settlement prosperity/
surplus producer." Village pillar's tenth category-keyed `world_
model` producer, and the first POSITIVE one in the whole cluster
(every prior producer names a hardship). New `SimulationEngine.
_detect_prosperity` (daily-metrics cadence, edge-triggered): both
`Settlement.materials` and `.currency` sustained past new `buildings.
PROSPERITY_MATERIALS_FRACTION`/`PROSPERITY_CURRENCY_FRACTION` (0.7 of
their respective capacities) at once — real broad-based prosperity,
not one resource's momentary spike.

New real consumer, deliberately NOT `_maybe_schedule_laws` (whose own
prompt is explicitly framed around "a hardship the village has
genuinely lived through" — folding a positive signal in there would
produce an incoherent prompt): `_maybe_schedule_festival`'s
`festival_chance` gains a new `PROSPERITY_FESTIVAL_BONUS` (0.3)
multiplicative boost while flagged — the positive counterpart to the
existing `FAMILY_FEUD_FESTIVAL_PENALTY` dampening a few lines above
it. "A comfortable village celebrates more, not automatically."

Verified: a direct production-path test for the producer (forms/
revises on a forced-full-coffers settlement, clears once resources
drop), a production-path test for the consumer through the real
`_maybe_schedule_festival` (a namespaced roll forced strictly between
the base and boosted chance flips the outcome only once prosperity is
flagged — genuine outcome-changing proof, not a formula check), a
4000-tick LLM-disabled soak with clean round-trip, `pyflakes` clean.
No native module touched. Tier 0 now has forty-six real converted
sites.

## Current state (v1.34.141)

Explicit user instruction: "Continue tier 0 ask is needed new
system," resolved via `AskUserQuestion` — "wildlife_recolonization as
a 9th law candidate." Same pure-consumer-side pattern as `disease_
outbreak`/`starvation_death`'s conversions: `wildlife_recolonization`
already had a real `pattern_signal_counts` counter and a real
`village_pillar` mirror (same `_bump_village_pattern_signal` call
site), previously consumed only by the ontology-proposal pressure-
signal tiebreak. Added as `candidates`' ninth entry plus a `_LAW_
PATTERN_TEXT` line — a settlement repeatedly seeing wildlife press
back into its farmland can now produce a real hunting-rights/land-use
law outright, or win a tie via the existing `village_pillar.subject_
confidence` tiebreak. `PRESSURE_SIGNAL_LABELS` already had a
`wildlife_recolonization` entry from earlier work, no change needed
there.

Verified: a production-path test confirming a lone `wildlife_
recolonization` signal at threshold wins outright and grounds the
real `laws` prompt, a 4000-tick LLM-disabled soak with clean
round-trip, `pyflakes` clean. No native module touched. Every
`PRESSURE_SIGNAL_LABELS`-backed pattern-signal category now also has
a real `_maybe_schedule_laws` consumer — this specific gap class is
fully closed. Tier 0 now has forty-five real converted sites.

## Current state (v1.34.140)

Explicit user instruction: "Continue tier 0." A ninth law candidate
needing no new producer, same pattern as `disease_outbreak`'s
conversion: `starvation_death` already had a real `pattern_signal_
counts` counter and a real `village_pillar` mirror (same `_bump_
village_pattern_signal` call site as `disease_outbreak`/`wildlife_
recolonization`), previously consumed only by the ontology-proposal
pressure-signal tiebreak. Added as `candidates`' eighth entry plus a
`_LAW_PATTERN_TEXT` line — a settlement repeatedly losing people to
hunger can now produce a real famine-relief/rationing law outright,
or win a tie via the existing `village_pillar.subject_confidence`
tiebreak. `PRESSURE_SIGNAL_LABELS` already had a `starvation_death`
entry from earlier work, no change needed there.

Verified: a production-path test confirming a lone `starvation_death`
signal at threshold wins outright and grounds the real `laws` prompt,
a 4000-tick LLM-disabled soak with clean round-trip, `pyflakes`
clean. No native module touched. Tier 0 now has forty-four real
converted sites (pure consumer-side — no new producer, since a real
one already existed).

## Current state (v1.34.139)

Explicit user instruction: "Continue tier 0 and ask me question for
new things to add," resolved via `AskUserQuestion` — "Currency
shortage producer." Village pillar's eighth category-keyed `world_
model` subject, same shape as `_detect_food_shortage`. New `SimulationEngine._detect_currency_shortage`
(daily-metrics cadence, edge-triggered) compares `Settlement.currency`
against new `buildings.CURRENCY_SHORTAGE_THRESHOLD=5.0` — half of the
existing `INVENTION_CURRENCY_THRESHOLD` (10.0, "prosperous enough to
invent"), i.e. 10% of `CURRENCY_CAPACITY` against invention's 20%, so
the new threshold is derived from an already-tuned constant rather
than picked from nothing.

New real consumer: `_maybe_schedule_laws`'s `candidates` dict gains a
genuine SEVENTH option — `"currency_shortage"` can now win the
`pattern_key` pick outright and produce a real taxation/currency law,
same shape every prior category-keyed producer established. Also
strengthens `_maybe_schedule_ontology_proposal`'s pressure-signal scan
for free. Added a matching `PRESSURE_SIGNAL_LABELS` entry.

Verified: a direct production-path test for the producer (forms/
revises on a forced-empty-coffers settlement, clears once currency
recovers), a production-path test for the consumer (a lone `currency_
shortage` signal at threshold wins outright and grounds the real
`laws` prompt), a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean. No native module touched. Tier 0 now has forty-three
real converted sites.

## Current state (v1.34.138)

Explicit user instruction: "Continue tier 0." A sixth law candidate
needing no new producer: `disease_outbreak` already had a real
`pattern_signal_counts` counter and a real `village_pillar` mirror
(via `_bump_village_pattern_signal`, wired at `_maybe_promote_ritual`'s
sibling loop, same batch as `starvation_death`/`wildlife_
recolonization`) — but was previously consumed only by the ontology-
proposal pressure-signal tiebreak, never by `_maybe_schedule_laws`.
Added as `candidates`' sixth entry plus a `_LAW_PATTERN_TEXT` line —
a settlement repeatedly seeing sickness take hold can now produce a
real public-health law outright, or win a tie against another
candidate via the existing `village_pillar.subject_confidence`
tiebreak, same shape `housing_shortage`/`food_shortage` established.
The post-enactment reset (`stl.pattern_signal_counts[pattern_key] =
0` for any non-theft winner) was already fully generic, no change
needed there.

Verified: a production-path test confirming a lone `disease_outbreak`
signal at threshold produces a real `laws` prompt naming it, a second
production-path test confirming a genuine tie against `food_shortage`
breaks toward `disease_outbreak` once `village_pillar` has real
confidence about it, a 4000-tick LLM-disabled soak with clean
round-trip, `pyflakes` clean. No native module touched. Tier 0 now
has forty-two real converted sites (pure consumer-side — no new
producer, since a real one already existed).

## Current state (v1.34.137)

Explicit user instruction: "Continue tier 0." Village pillar's seventh
category-keyed `world_model` subject, same shape as `_detect_housing_
shortage` — this one keyed by the literal `"food_shortage"` string.
New `SimulationEngine._detect_food_shortage` (daily-metrics cadence,
edge-triggered) reuses `Population._granary_fill_ratio` (already
computed for `_maybe_migrate`'s hunger-driven pull signal) and
`world.reactions.FOOD_SHORTAGE_FILL_THRESHOLD` (the exact threshold
`_maybe_tick_composite_reactions`'s own inline `food_shortage_now`
check already uses for the "Desperate Times" combination) rather than
duplicating either.

New real consumer: `_maybe_schedule_laws`'s `candidates` dict gains a
genuine FIFTH option — `"food_shortage"` can now win the `pattern_key`
pick outright and produce a real law, same shape `housing_shortage`
already established. Also strengthens `_maybe_schedule_ontology_
proposal`'s pressure-signal scan for free (it already reads every
`pattern_signal_counts` key). Added `"housing_shortage"`/`"food_
shortage"` entries to `llm/ontology.py`'s `PRESSURE_SIGNAL_LABELS` for
consistent wording there too.

Verified: a direct production-path test for the producer (forms/
revises in place on a forced empty-granary settlement, clears once
granaries fill), a production-path test for the consumer (a lone
`food_shortage` signal at threshold wins outright and grounds the
real `laws` prompt, ticking the clock to the job's real staggered
day-of-month), a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean. No native module touched. Tier 0 now has forty-one
real converted sites.

## Current state (v1.34.136)

Explicit user instruction: "Continue tier 0." Same bug class as
v1.34.135, found by extending that pass's own search technique to the
last remaining `PRESSURE_SIGNAL_LABELS` key: `nature_adaptation`'s
existing mirror (`_maybe_schedule_nature_mind`'s apply(), a genuinely
NEW nature belief) writes into `nature_pillar.world_model` keyed by
Nature's own free-text belief subject (e.g. "the vanished predator
packs") — but `_maybe_schedule_ontology_proposal`'s tiebreak reads
`village_pillar.subject_confidence("nature_adaptation")` (a different
pillar AND a different, literal subject), so this key's tiebreak
input was a silent permanent no-op despite the counter itself being
real and already able to win outright. Reused the same `_bump_village_pattern_signal` helper v1.34.135
introduced, called from the same site the counter itself already
increments.

Verified: a direct production-path test through the real `_maybe_
schedule_nature_mind` apply() (a genuine new-belief firing forms the
village_pillar mirror), a production-path test through the real
`_maybe_schedule_ontology_proposal` confirming a genuine tie now
leans toward `nature_adaptation` via this real content, a 4000-tick
LLM-disabled soak with clean round-trip, `pyflakes` clean. No native
module touched. Tier 0 now has forty real converted sites. Every
`PRESSURE_SIGNAL_LABELS` key (`materials_bottleneck`/`dispute_feud`/
`starvation_death`/`disease_outbreak`/`wildlife_recolonization`/
`nature_adaptation`) now has a real matching `village_pillar` mirror —
this specific gap class is closed.

## Current state (v1.34.135)

Explicit user instruction: "Continue tier 0." Village pillar's sixth,
seventh, and eighth category-keyed `world_model` subjects, all in one
batch since they share the exact same shape and consumer: `starvation_
death`/`disease_outbreak`/`wildlife_recolonization` were already real
`pattern_signal_counts` keys with a real `PRESSURE_SIGNAL_LABELS`
entry in `llm/ontology.py`, and `_maybe_schedule_ontology_proposal`'s
pressure-signal tiebreak (v1.34.129/131) already scans the WHOLE
`pattern_signal_counts` dict and already reads `village_pillar.
subject_confidence(kv[0])` for whichever key wins — but none of these
three had a matching mirror anywhere, so a genuine tie involving one
of them could never lean toward it (the real occurrence count could
still win outright on its own, just never break a tie). New shared
`SimulationEngine._bump_village_pattern_signal(subject, text)` helper
(factored out since this is the third site needing the exact revise-
in-place shape `dispute_feud`/`materials_bottleneck` already
established) is called from `_detect_ritual_signals`'s existing three
increment sites — the same place these counters were already being
bumped, no new detection logic needed.

Verified: a direct production-path test through the real `_detect_
ritual_signals` (forms/revises in place across two firings), a
production-path test through the real `_maybe_schedule_ontology_
proposal` confirming a genuine tie now leans toward `starvation_death`
via this real new content (not a self-seeded stand-in), a 4000-tick
LLM-disabled soak with clean round-trip, `pyflakes` clean. No native
module touched. Tier 0 now has thirty-nine real converted sites (one
new shared helper backing three subjects, counted as the single
producer-side conversion it mechanically is).

## Current state (v1.34.134)

Explicit user instruction: "Build new sites in tier 0 so that we can
move forward." Village pillar's fifth category-keyed `world_model`
producer, this one keyed by a literal `"housing_shortage"` string.
New `SimulationEngine._detect_housing_shortage` (daily-metrics
cadence, edge-triggered, same shape as `_detect_occupation_shortage`):
reuses `Population._housing_pressure` (population / hut capacity,
already computed for `_maybe_migrate`'s disaster-refugee push signal,
§2 "refugees after disasters") rather than duplicating the capacity
math — a settlement genuinely crossing INTO overcrowding
(`MIGRATION_HOUSING_PRESSURE_THRESHOLD`) mirrors/revises a village
belief keyed by that literal string.

New real consumer: `_maybe_schedule_laws`'s `candidates` dict gains a
genuine FOURTH option (not just a tiebreak input) — `"housing_
shortage"` can now win the `pattern_key` pick outright and produce a
real law, same shape `materials_bottleneck` already established there
(v1.34.120). The existing reset-on-enactment logic was already
generalized to any non-theft key, so no further change was needed
there.

Verified: a direct production-path test for the producer (forms/
revises in place on a forced overcrowded settlement, clears on
recovery), a production-path test for the consumer (a lone `housing_
shortage` signal at threshold wins outright and grounds the real
`laws` prompt, ticking the clock to the job's real staggered day-of-
month rather than faking the gate), a direct tiebreak test confirming
the new candidate participates correctly in a 4-way tie, a 4000-tick
LLM-disabled soak with clean round-trip, `pyflakes` clean. No native
module touched. Tier 0 now has thirty-eight real converted sites.

## Current state (v1.34.133)

Explicit user instruction: "Continue tier 0 and parallely you can
audit too." Docs-only — extended the audit to every remaining
`max`/`min`/`key=` candidate-list pick in `agents/population.py` not
already pillar-leaned, looking for a genuine new Tier 0 site. Two
confirmed-correct existing sites re-checked against real content
(`ontology_evolution`'s fitness-weighted parent pick and merge-pair
pick both read `innovation_pillar.subject_confidence(c.name)` against
concepts that ARE mirrored by that literal name at proposal time —
real, not another dead consumer).

One near-miss investigated and ruled out, not converted:
`Population.council_faction_majority`'s internal `max(counts, ...)`
tiebreak looked like a candidate at first glance, but is provably
inconsequential — two factions can never BOTH exceed 50% of a
council's living members, so whenever the `max` pick is genuinely
tied, the subsequent `>50%` gate returns `None` regardless of which
tied faction was chosen. Threading a pillar lean into it would change
nothing observable; correctly left alone rather than converted for
appearance's sake.

Every other remaining candidate-list pick in `population.py`
(memory/lesson/belief eviction by tick, damaged-building sort, bonded-
partner pick, elder/challenger council-seat picks) is either a real-
signal pick with only a same-tick or same-condition tie too rare to be
worth threading a lean through, or already covered by an existing
site. No new site converted this pass — same "the audit is the work"
conclusion as v1.34.132, extended to a second file. Tier 0 stays at
thirty-seven real converted sites, all now cross-checked twice.

## Current state (v1.34.132)

Explicit user instruction: "Continue tier 0 and parallely you can
audit too." Docs-only — broadened v1.34.131's self-audit to every
`subject_confidence(...)` consumer in `simulation/engine.py`, checking
specifically for the "provably always zero" bug class (a consumer
reading a pillar/subject a real producer never writes to) rather than
the weaker "fuzzy substring/word-overlap match sometimes misses"
class this project already knowingly accepts at several sites
(`_village_priority_lean`'s growth/caution keyword scan, the omen
subject lean — both explicitly documented in their own docstrings as
best-effort, correctly 0.0 when nothing matches).

No further hard bugs found. The FAMILY/COUNCIL institution-name
lookups (`_maybe_tick_composite_reactions`' feuding-pair tiebreak,
`_maybe_schedule_institution_belief`'s target lean, `_maybe_schedule_
rule_proposal`'s stuck-institution tiebreak) all read `village_pillar.
subject_confidence(institution.name)` — confirmed these already sit in
the same accepted "no guaranteed producer, honest best-effort" class
(the feuding-pair site's own comment already says so: "never a real
priority signal here — there isn't one"), NOT the provable-zero class
the two v1.34.131 fixes were. GUILD's version of the same lookup is
structurally sound and unaffected: `institution.name` for a GUILD is
literally the skill string, a real substring match against the
guild-founding mirror's `"the {skill} guild"` subject.

Every `humans_pillar.subject_confidence(agent.name)` site (the large
majority of Tier 0's converted sites) is backed by the real, confirmed
per-agent producer (v1.34.98). Every `nature_pillar.subject_
confidence(species)` site is backed by the real species-keyed producer
(v1.34.107). No new site converted this pass — the audit itself was
the work.

Explicit user instruction: "Continue tier 0." Self-audit, not a new
site: re-checked this session's own three prior conversions
(v1.34.128-130) against their REAL production content rather than
trusting their own self-seeded unit tests, and found two genuine
dead-consumer bugs of the exact same class v1.34.130 just fixed for
`era_branch` — both fixed this pass.

(1) `_maybe_schedule_ontology_proposal`'s pressure-signal tiebreak
(v1.34.129) read `innovation_pillar.subject_confidence(kv[0].replace(
"_", " "))`, but every real producer of those exact
`pattern_signal_counts` keys (`dispute_feud`/`materials_bottleneck`,
see their own mirror sites) writes into `village_pillar`, keyed by the
literal underscored string, not a space-separated label read from a
different pillar — the tiebreak was a silent permanent no-op in
production; the unit test that "passed" had manually seeded
`innovation_pillar` itself, masking the mismatch. Fixed to read
`village_pillar.subject_confidence(kv[0])` directly, re-verified
against the REAL `village_pillar` mirror content this time (not a
self-seeded stand-in).

(2) `_maybe_spread_tradition_keeping`'s pillar-leaned pick (v1.34.128)
read `village_pillar.subject_confidence(t)` for each full "{name}:
{description}" tradition string, but `_maybe_schedule_tradition`'s
apply() only ever called `village_pillar.remember()` (memory-only) —
`subject_confidence` scans `world_model`, never `memory`, so there was
never any real content to match. New: that apply() now also mirrors a
`village_pillar.world_model` entry keyed by the bare tradition NAME (a
prefix of the full stored string, so the consumer's substring check
matches it), revised in place if the same name is ever re-coined.

Verified: both fixes re-confirmed via production-path tests that seed
the REAL producer's own mirror shape (not a manual stand-in) —
`village_pillar.upsert_world_model(subject="dispute_feud", ...)` for
(1), the real `_maybe_schedule_tradition` apply() for (2), confirming
`subject_confidence` on the exact strings the real consumers pass now
returns real nonzero values — plus a 4000-tick LLM-disabled soak with
clean round-trip, `pyflakes` clean. Tier 0 still at thirty-seven real
converted sites (no new site — two of the existing thirty-seven are
now actually load-bearing instead of silently inert). Lesson for
future Tier 0 work, recorded rather than just fixed: a producer/
consumer pairing needs its OWN production-path check against the
real mirror site, not a hand-seeded pillar entry in the unit test —
the two bugs this pass found both would have been caught immediately
by that discipline.

## Current state (v1.34.130)

Explicit user instruction: "Continue tier 0," resolved via
`AskUserQuestion` after a codebase-wide re-scan (population.py,
llm/*.py, world/*.py, settlement/*.py) found no further real-signal-
plus-arbitrary-tiebreak sites: "Design a new producer."

Found a genuine, previously-unnoticed dead consumer rather than
inventing a new mechanism from scratch: `era_branch.compute_branch`'s
own `pillar_leans` param (Tier 0's SECOND site, v1.34.47) reads
`innovation_pillar.subject_confidence(branch)` keyed by the literal
branch name ("industrious"/"scholarly"/"devout"/"mercantile"/
"agrarian") — but `_maybe_schedule_era_branch`'s own mirror has only
ever written a per-SETTLEMENT subject (`"{name}'s tech-path lean"`),
so that read was a permanent no-op across every settlement that ever
hit a real branch tie (including the common all-zero case: a
settlement entering its first branch-eligible era with nothing
matching built yet). Added a second mirror entry keyed by the literal
branch name itself, revised in place across every settlement that
leans that way — a branch other settlements have already leaned into
is now a real cross-settlement signal the next tied settlement can
read, unblocking a two-and-a-half-year-old dead read.

Verified: a production-path test through the real
`_maybe_schedule_era_branch` (a genuine all-tied first-branch-era
settlement; a seeded lean toward a branch other than the unleaned
control's random pick flips the outcome to the leaned branch; the
unleaned control reproduces the original random tiebreak), a
producer-side test confirming the branch-keyed entry forms then
revises in place (not duplicates) across two separate firings that
land on the same branch, a 4000-tick LLM-disabled soak with clean
round-trip, `pyflakes` clean. Tier 0 now has thirty-seven real
converted sites.

## Current state (v1.34.129)

Explicit user instruction: "Continue tier 0." Thirty-sixth
conversion: `_maybe_schedule_ontology_proposal`'s pressure-signal pick
(which of a settlement's crossed-threshold `pattern_signal_counts`
categories names the "problem" Innovation's proposal is grounded in,
feeding `llm/ontology.py`'s real prompt content) was a flat `max` over
counts alone — a real, not rare, tie whenever two categories cross the
threshold the same season, previously resolved by dict-iteration
order. Now `max`'s key is `(count, innovation_pillar.subject_
confidence(label))` — the real occurrence count stays the sole
determinant except on a genuine tie, where the category Innovation's
own attention already leans toward wins. No lean anywhere reproduces
the exact prior dict-order pick.

Verified: a direct tuple-key test (no-lean/tiebreak-flip/real-signal-
never-overridden), a production-path test through the real
`_maybe_schedule_ontology_proposal` (a genuine two-category tie; the
leaned run's prompt names "bitter disputes and feuding," the unleaned
control still names "a shortage of building materials"), a 4000-tick
LLM-disabled soak with clean round-trip, `pyflakes` clean. Tier 0 now
has thirty-six real converted sites.

## Current state (v1.34.128)

Explicit user instruction: "Continue tier 0 ... keep building more
sites." Thirty-fifth conversion: `_maybe_spread_tradition_keeping`'s
WHICH-tradition-to-spread-this-tick pick was flat `rng.choice(
settlement.traditions)` — no real signal ever consulted, unlike the
prior "real signal + arbitrary tiebreak" sites. New `TRADITION_
PILLAR_LEAN_WEIGHT=0.4` folds `village_pillar.subject_confidence
(tradition)` into a weighted `rng.choices` draw — the tradition
Village's own accumulated theory already favors is now measurably
more likely to spread to a new personal keeper. All-zero-confidence
(the common case for a fresh tradition) reproduces a uniform draw,
verified statistically; the RNG-consumption pattern itself is NOT
byte-identical to plain `rng.choice` (same acknowledged, documented
class of change as v1.34.109's `_maybe_schedule_personal_belief`
conversion — this project doesn't require determinism, only that the
distribution holds).

Verified: a direct 20,000-trial statistical test (uniform baseline,
seeded-lean bump), a production-path smoke test through the real
`_maybe_spread_tradition_keeping` (a seeded village belief measurably
produces a keeper for the favored tradition within 4000 ticks), a
4000-tick LLM-disabled soak with clean round-trip, `pyflakes` clean.
Tier 0 now has thirty-five real converted sites.

## Current state (v1.34.127)

Explicit user instruction: "Continue tier 0," resolved via `AskUserQuestion`
following a codebase-wide re-scan finding no more real-signal-plus-
arbitrary-tiebreak sites: "Design a new producer (Recommended)."

Village pillar's fourth category-keyed `world_model` producer, this
one keyed by a literal `occupations.py` occupation string. New
`SimulationEngine._detect_occupation_shortage` (daily-metrics cadence,
edge-triggered): a settlement with real population (>= `OCCUPATION_
SHORTAGE_POPULATION_THRESHOLD=15`) and zero living holders of some
occupation (MAYOR excluded — its 1-holder cap makes zero normal, not
scarce) mirrors/revises a village belief keyed by that occupation.

New real consumer: `_maybe_assign_occupations`'s least-represented-
occupation pick gains `Population.OCCUPATION_PILLAR_LEAN_MAX=0.5` as a
tuple-key tiebreak — real counts always dominate, the lean only
resolves genuine ties among equally-scarce occupations (the common
early-game case). `occupation_pillar_lean` computed once per tick in
`World.tick()` over `ALL_OCCUPATIONS` (~13 entries), same "compute
once over a small fixed set" pattern as `building_kind_pillar_lean`.

Verified: direct production-path tests for both the producer (forms/
revises/stays-silent/clears-on-recovery) and the consumer (no-lean vs.
seeded-lean pick), a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean. No native module touched. Tier 0 now has thirty-four
real converted sites.

## Current state (v1.34.126)

Explicit user instruction: "Convert as many sites of tier 0 as you can
in this turn." Two more sites, same real-signal-plus-arbitrary-`-id`-
tiebreak shape as the prior two sessions.

Thirty-second: `_maybe_rotate_core_cast`'s outgoing (`min`)/incoming
(`max`) picks were both `(prominence, -id)` — real signal, arbitrary
tiebreak on ties (common: several near-zero-prominence candidates).
New `Population.CORE_CAST_ROTATION_HUMANS_LEAN_MAX=0.15` folds
`humans_pillar.subject_confidence(agent.name)` in with the SAME sign
both directions: under `min` a higher lean protects a tied candidate
from demotion, under `max` it favors a tied candidate for promotion —
same regard, read oppositely depending on which side of the swap.
Wired directly at the engine.py monthly-job call site via a lazy
lambda (no per-tick cost).

Thirty-third: `_maybe_collectivize_excess_population`'s (D6) removal-
candidate sort was pure `_prominence` ascending, same arbitrary-tie
shape. New `Population.DISTRICT_HUMANS_LEAN_MAX=0.15` — a higher lean
sorts a tied agent later, protecting them from being folded into a
district. Both sites' `humans_lean=None` reproduce the exact prior
ordering.

Verified: direct tuple-key tests for both (tie flip, real signal never
overridden), production-path tests through both real scheduling
functions (a forced tied-prominence rotation swap; a monkeypatched
small `DISTRICT_INDIVIDUAL_CAP` with three tied agents), a 4000-tick
LLM-disabled soak with clean round-trip, `pyflakes` clean. No native
module touched. Tier 0 now has thirty-three real converted sites.

## Current state (v1.34.125)

Explicit user instruction: "Continue tier 0." Thirty-first conversion:
`_apply_inheritance`'s heir pick (`max(candidates, key=(bond, -id))`)
had a real primary signal (relationship strength) but an arbitrary
`-id` tiebreak that fires whenever two family candidates never
actually interacted with the deceased (both default to 0.0 bond —
the common case). New `Population.HEIR_HUMANS_LEAN_MAX=0.15` folds
`humans_pillar.subject_confidence(agent.name)` in as a second tuple
key, ahead of `-id` but behind the real bond value — a genuine bond
difference can never be overridden, only the arbitrary fallback is
replaced with something meaningful. No new wiring needed: `_apply_
deaths`/`_apply_inheritance` reuse the same `humans_lean` callable
already threaded through `Population.tick()` for v1.34.124's HUT-owner
site — `World.tick()`'s existing lazy lambda reaches this site free.

Verified: a direct tuple-key test (no-lean ties toward lowest id, a
seeded lean flips the tie, a genuine bond difference stays dominant),
a production-path test through the real `_apply_inheritance` (a HUT's
owner transfers to the tied lowest-id candidate with no lean, to the
leaned candidate with one), a 4000-tick LLM-disabled soak with clean
round-trip, `pyflakes` clean. No native module touched. Tier 0 now has
thirty-one real converted sites.

## Current state (v1.34.124)

Explicit user instruction: "Continue tier 0." Thirtieth conversion:
`_maybe_start_construction`'s HUT-owner pick (already ambition-
weighted, same shape as `deliberate_guild_candidate`'s founder pick
and `fission_candidate`'s leader pick) now also weighs `humans_pillar.
subject_confidence(agent.name)` via new `Population.HUT_OWNER_HUMANS_
LEAN_MAX=0.2` — real ambition stays dominant. Since `Population` stays
decoupled from pillar state and this site's surrounding scan runs
every tick (only rarely reaching the HUT branch itself), the pillar
lookup is threaded as a lazy callable, same technique `due_for_
dispute` established — `World.tick()` passes `lambda a: self.
humans_pillar.subject_confidence(a.name)` through `Population.tick()`,
only ever invoked against the small eligible founder list actually
being weighed.

Verified: a direct weight-formula test, a 400-trial production-path
statistical test through the real `_maybe_start_construction` (no-lean
favors ambition 240/400; a seeded lean toward the low-ambition agent
raises their win rate 179/400 -> 202/400), a 4000-tick LLM-disabled
soak with clean round-trip, `pyflakes` clean. No native module
touched. Tier 0 now has thirty real converted sites.

## Current state (v1.34.123)

Explicit user request: a pasted live "long live run diagnostics"
report (42,013 ticks) — "expose more diagnostics if you think it
would help debugging things deeper and also fix issues from this
report."

Real bug fixed, the exact "unreachable threshold" bug class this file
already documents for flood/snow/wind (v0.88.0/v1.34.64):
`wildfire_ignition_ticks_recorded: 0` for the whole run traced to
`WILDFIRE_DRY_PRECIPITATION=0.1` sitting below `compute_weather`'s own
realized summer-minimum precipitation (~0.145, measured directly via
10 seeds x 4 years driven with a real `SimClock`) — wildfires were
structurally impossible regardless of chance/temperament/heatwave
tuning. Raised to 0.25 (this measurement's own ~19th percentile);
verified via a 20-seed x 20-year production-path run producing 20 real
ignitions against 15 expected.

Two new diagnostics, both closing a specific "had to hand-derive this"
gap the report exposed rather than a speculative add: `llm_stats.
reasoning.calls_near_timeout` (`llm/jobs.py`) — succeeded-only latency
percentiles can't show a deployment where most reasoning calls are
timing out (survivorship gap), so a succeeded call within 85% of its
own real timeout ceiling now increments a leading-indicator counter;
`llm_backpressure_pressure_band` ("healthy"/"elevated"/"severe",
`_backpressure_pressure_band()`) surfaces WHY `llm_backpressure_
limit_effective` sits where it does instead of requiring a manual
cross-reference against `ADAPTIVE_LATENCY_ELEVATED/SEVERE_MS`.

Investigated, deliberately not changed: the report's large backpressure-
drop count is `_current_backpressure_limit()` correctly tightening to
its `llm_max_concurrent` floor under genuinely severe measured
latency, not a scheduling bug — re-tuning `llm_max_concurrent` again
needs the user's own live-comparison call, per this project's own
repeated history on that exact constant, not a guess from one report.
The empty `reflection_notebook` matches v1.23.1's already-documented
Reflection cold-start latency (~70k ticks for first output) — not a
bug, this report's 42,013 ticks hasn't reached it yet.

Verified: direct unit tests for both new diagnostics, a direct 20-seed
x 20-year `tick_wildfire` production-path test, `pyflakes` clean, a
4000-tick LLM-disabled soak with clean round-trip. No native module
touched.

## Current state (v1.34.122)

Explicit user decision via `AskUserQuestion`: "Reopen choose_
building_kind" — the one remaining big Tier 0-adjacent lever, a
deliberately reopened, already live-diagnostic-tuned system.
`buildings.choose_building_kind` gained a `pillar_lean` param applied
AFTER `PRIORITY_KIND_BOOST`/`ERA_BRANCH_BOOST` via a new, deliberately
smaller `BUILDING_KIND_PILLAR_LEAN_MAX=1.15` — real cultural momentum
("the village keeps building what it tends to build"), subordinate to
both existing tuned signals. `pillar_lean=None` reproduces the exact
prior weights/RNG-consumption pattern byte-for-byte.

New producer: `Population._maybe_start_construction`'s real
`"construction_started"` life event is the one place engine.py can
recover WHICH kind was chosen (parsed off its own stable shared
description template, since `Population` doesn't reference pillar
state) — mirrored into `village_pillar.world_model` keyed by the
literal kind value, revised in place. `World.tick()` computes the
full lean dict once per tick (cheap, bounded), threaded through
`Population.tick` -> `_maybe_start_construction` -> `choose_building_
kind`.

Verified: a direct RNG-parity test, a direct statistical test (leaned
kind's share rises), a production-path statistical test through the
real `_maybe_start_construction` on real world terrain, a production-
path test through the real `_tick_once` (mirror forms/revises), a
real `World.tick()` smoke test, a 4000-tick LLM-disabled soak with
clean round-trip, `pyflakes` clean across all four touched files. No
native module touched. Tier 0 now has twenty-nine real converted
sites.

## Current state (v1.34.121)

Explicit user instruction: "Convert more sites and ask if you get
stuck." `Population.deliberate_guild_candidate`'s skill pick had a
fixed `(farming, construction, medicine)` tuple-order bias — whichever
skill came first won outright whenever two qualified the same month.
No new producer needed: `_maybe_schedule_guild_founding`'s existing
`"the {skill} guild"` mirror (v0.64.0-era) already gives `subject_
confidence` real content to match a bare skill name against. New
`skill_lean: dict[str, float] | None` param; collect every qualifying
skill first, then `max` by lean — first-max-wins reproduces the exact
prior fixed-order pick with no lean anywhere.

Verified: a direct test (two simultaneously-qualifying skills, no-lean
picks farming, a seeded lean flips to construction), a production-path
test through the real `_maybe_schedule_guild_founding`, a 4000-tick
LLM-disabled soak with clean round-trip, `pyflakes` clean. Tier 0 now
has twenty-eight real converted sites.

## Current state (v1.34.120)

Explicit user decision via `AskUserQuestion`: "Yes new producer"
(Recommended) — extends v1.34.118's Village category-keyed producer
with a third subject. `_detect_settlement_bottlenecks`'s existing
edge-trigger now also mirrors `village_pillar.world_model` keyed by
the literal word `"materials_bottleneck"`, revised in place. Unlike
dispute_feud/theft (tiebreak inputs only), this is a genuine THIRD
*candidate* in `_maybe_schedule_laws`'s `candidates` dict — its own
real occurrence count can win the `pattern_key` pick outright and
produce an actual law, not just break a tie.

Real bug caught and fixed while wiring the third candidate: the post-
formation reset was hardcoded `if pattern_key == "theft": ... else:
reset dispute_feud` — with three real candidates this would reset the
WRONG signal whenever materials_bottleneck won. Generalized to
`stl.pattern_signal_counts[pattern_key] = 0` for any non-theft winner.

Verified: production-path tests through the real `_detect_settlement_
bottlenecks` (mirror forms) and `_maybe_schedule_laws` (materials_
bottleneck wins outright as sole eligible candidate, a real `forms:
true` apply() resets only its own counter), a regression test
confirming theft-wins still resets correctly, a 4000-tick LLM-disabled
soak with clean round-trip, `pyflakes` clean. Tier 0 now has
twenty-seven real converted sites.

## Current state (v1.34.119)

Explicit user instruction: "Convert more sites and ask if you get
stuck." Twenty-sixth conversion: `_maybe_tick_composite_reactions`'s
`feuding_pair` pick (which settlement-wide feuding FAMILY pair a
matching `relationship_rupture` composite reaction escalates) never
had a real priority signal to preserve — `next(...)` just returned
whichever pair nested iteration found first. Rewritten to collect
every feuding pair, then pick via `village_pillar.subject_confidence`
summed over both family names ONLY when 2+ pairs exist (the common
0-or-1-pair tick pays no new cost) — a genuine first-max-wins uniform
pick, same shape as several earlier Humans-lean sites.

Verified: a production-path test through the real `_maybe_tick_
composite_reactions` (two synthetic feuding pairs, a forced matching
reaction, no-lean picks first-found, a seeded belief flips the pick),
a 4000-tick LLM-disabled soak with clean round-trip, `pyflakes` clean.
Tier 0 now has twenty-six real converted sites.

## Current state (v1.34.118)

Explicit user instruction: "Yes new producer" — resolves the flagged
dead end (a broad sweep found no further genuinely-reachable tiebreak
site) by building Village's own category-keyed `world_model` producer,
the same shape Nature's species-keyed producer (v1.34.106/107)
established but Village had never had (only settlement/institution/
agent-keyed subjects so far). Two touch points: `_maybe_schedule_
dispute`'s real `apply()` mirrors keyed by the literal word `"dispute_
feud"` on a genuine feud outcome; `_tick_once`'s per-tick `last_life_
events` loop mirrors keyed by `"theft"` whenever a theft occurs
(`Population.law_signal_counts["theft"]`'s own increment lives in
`population.py`, decoupled from pillar access — `last_life_events` is
the one place engine.py sees it). Both revise in place via `find_
world_model_entry`. Real consumer: `_maybe_schedule_laws`'s `pattern_
key = max(candidates, key=candidates.get)` — a real occurrence-count
tie between `"theft"` and `"dispute_feud"` now breaks toward whichever
category `village_pillar` already has a standing theory about.

Verified: a direct test of the revise-in-place mechanics, production-
path tests through the real `_tick_once` (theft mirror forms/revises),
the real `_maybe_schedule_dispute` apply() (a forced feud outcome
forms the mirror), and the real `_maybe_schedule_laws` (a genuine tie,
no-lean picks theft, a seeded belief flips it to dispute_feud), a
4000-tick LLM-disabled soak with clean round-trip, `pyflakes` clean.
Tier 0 now has twenty-five real converted sites.

## Current state (v1.34.117)

Explicit user instruction: "Keep converting as many sites as you can,
if ever stuck ask." A broad re-sweep across `simulation/engine.py`,
`agents/population.py`, and the `world`/`settlement`/`llm` modules
found one further Phase-G-adjacent candidate, flagged via
`AskUserQuestion` rather than guessed since it's likely a near-
permanent no-op: `_apply_consciousness_intervention`'s `false_memory`
emotional-contagion partner pick (`max(primary.relationships, key=...)`
over a continuously-nudged float, so an exact tie is rare, unlike the
faction/omen/observer sites). Explicit user decision: convert anyway,
for consistency. `max`'s key gained `humans_pillar.subject_confidence
(partner.name)` as a tie-break-only second element — real bond
strength stays the sole determinant.

Verified: a direct test (tie-break flip, real-signal-never-overridden),
a production-path test through the real `_apply_consciousness_
intervention("false_memory", ...)`, a 4000-tick LLM-disabled soak with
clean round-trip, `pyflakes` clean. Tier 0 now has twenty-four real
converted sites — a broad sweep found no further genuinely-reachable
tiebreak site; remaining unconverted sites need either new content
design (like Nature's species-keyed producer) or another explicit
decision naming a specific site.

## Current state (v1.34.116)

Explicit user decision via `AskUserQuestion` on both sites flagged
last turn as needing a call — both approved.

Twenty-second conversion: `Population._detect_faction_candidate`'s
cluster pick (which trust-graph cluster gets named as a new faction)
gained the same "real primary signal, pillar lean only as pure
tiebreak" shape as sites 1, 2, and 21 — `max`'s key is now `(cohesion
(c), len(c), cluster_lean(c))`, where `cluster_lean` averages `humans_
pillar.subject_confidence` over the cluster's own members. Real
cohesion/size stay the sole determinant except in a genuine tie.

Twenty-third conversion: `_observer_favorite_agent`'s tie-break among
equally-most-viewed core-cast agents (which feeds Phase G's monthly
consciousness interventions — false memories, omen subjects,
misplaced objects) extends v1.34.9/v1.34.114's Phase G carve-out:
`sorted`'s key gained `humans_pillar.subject_confidence(agent.name)`
as a second, tie-breaking-only element. Real view count stays the
sole determinant; never changes whether an intervention happens or
its content, only which tied agent it targets.

Verified: direct tests for both sites (faction tiebreak flip +
real-size-never-overridden; consciousness tiebreak flip +
real-view-count-never-overridden), a production-path test through the
real `_maybe_schedule_faction`, a 4000-tick LLM-disabled soak with
clean round-trip, `pyflakes` clean. Tier 0 now has twenty-three real
converted sites.

## Current state (v1.34.115)

Explicit user instruction: "Convert as many sites as you can."
Twenty-first Tier 0 conversion: `_maybe_schedule_rule_proposal`'s
`stuck_institution` pick (which institution's unmet objective grounds
a proposed rule) gained the same "real primary signal, pillar lean
only as pure tiebreak" shape as the very first two Tier 0 sites
(`town_brain.compute_priority`/`era_branch.compute_branch`) —
`max`'s key is now `(objective_ticks_unmet, village_pillar.
subject_confidence(institution.name))`, so the real unmet-objective
duration stays the sole determinant except when two institutions are
genuinely tied, at which point the one Village's own accumulated
theory already leans toward wins. No lean anywhere reproduces the
exact prior first-found tie-break.

Verified: a direct logic test (tie-break, no-lean parity, real signal
never overridden), a production-path test through the real
`_maybe_schedule_rule_proposal`, a 4000-tick LLM-disabled soak with
clean round-trip, `pyflakes` clean. Tier 0 now has twenty-one real
converted sites.

## Current state (v1.34.114)

Explicit user decision via `AskUserQuestion` on both sites flagged
last turn as needing a call — both approved.

Nineteenth conversion: `Population.due_for_dispute` previously
returned the FIRST eligible festering pair found each tick. Explicit
user decision to accept the added per-tick cost: now every eligible
pair is collected, then a lazy `humans_lean` callable (bounds the
`humans_pillar.subject_confidence` scan to actual candidates, not the
whole population) picks among them via `max`. Only the chosen pair's
cooldown is set.

Twentieth conversion: `_maybe_schedule_omen`'s subject-candidate pick
now leans toward whichever candidate `nature_pillar` already has
confidence about (`NATURE_OMEN_SUBJECT_LEAN_MAX=0.4`), extending
v1.34.9's one-time Phase G carve-out from omen's own mirror write to
this pick specifically. Every other Phase G ambiguity rule stays
unchanged; honestly often a no-op since Nature's content is
ecological, not usually agent-named.

Verified: a direct `due_for_dispute` test (no-lean vs. seeded-lean,
cooldown-only-on-chosen-pair), production-path tests through both real
scheduling functions, a 4000-tick LLM-disabled soak with clean
round-trip, `pyflakes` clean. Tier 0 now has twenty real converted
sites.

## Current state (v1.34.113)

Explicit user instruction: "Build as many sites as possible in this
turn." Eighteenth conversion, simpler than the letter site since
`Population.core_migration_candidates` already returns the FULL
eligible list — only `_maybe_schedule_migration_decision`'s own
`candidates[0]` pick needed to change. Now `max(candidates, key=
lambda c: humans_pillar.subject_confidence(c[0].name))`, same
first-max-wins-preserves-no-lean-behavior discipline as `letter`.

Verified: a production-path test through the real `_maybe_schedule_
migration_decision` (two core-cast agents forced eligible, the
decision roll forced to pass; no-lean picks iteration order, a seeded
belief flips it), a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean. Tier 0 now has eighteen real converted sites.

## Current state (v1.34.112)

Explicit user instruction: "Build as many sites as possible in this
turn." Seventeenth conversion: `Population.fission_candidate`'s
leader pick among already-eligible would-be leaders had the exact
same shape as `deliberate_guild_candidate`'s founder pick — gained the
same `humans_lean` treatment, reusing `GUILD_FOUNDER_HUMANS_LEAN_MAX`
unchanged (same trait scale, no reason to tune differently). Simpler
than the guild site: the eligibility filter here already runs BEFORE
the pick, so a lean can only reorder among candidates already known to
be ambitious enough — no separate floor re-check needed. `_maybe_
schedule_fission` computes the lean dict from `humans_pillar.subject_
confidence(agent.name)` over all living agents.

Verified: a direct test against a real `Population` built via `spawn_
initial` (no-lean picks the more-ambitious leader, a seeded lean flips
it), a production-path test through the real `_maybe_schedule_
fission`, a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean. Tier 0 now has seventeen real converted sites.

## Current state (v1.34.111)

Explicit user instruction: "Continue tier 0." Sixteenth conversion:
`Population.deliberate_guild_candidate`'s founder pick among tied-
eligible masters (previously purely `TRAIT_AMBITION`-driven) gains an
optional `humans_lean` param — the master Humans' own attention
already returns to can edge out a marginally-more-ambitious rival.
New `GUILD_FOUNDER_HUMANS_LEAN_MAX = 0.2` bounds the lean against
traits' `[-1, 1]` range; `_maybe_schedule_guild_founding` computes it
from `humans_pillar.subject_confidence(agent.name)`. The eligibility
floor (`DELIBERATE_GUILD_FOUNDER_AMBITION`) still reads each
candidate's REAL, unmodified trait afterward — a lean can shift who's
considered, never manufacture an unqualified founder.

Verified: a direct test (no-lean picks the more-ambitious master, a
seeded lean flips it, a large lean can't approve a founder below the
real ambition floor), a production-path test through the real
scheduling function, a 4000-tick LLM-disabled soak with clean
round-trip, `pyflakes` clean. Tier 0 now has sixteen real converted
sites.

## Current state (v1.34.110)

Explicit user instruction: "Continue." Fifteenth conversion.
`_maybe_schedule_letter`'s cross-settlement letter-writer search
previously stopped at the FIRST eligible core-cast sender in
`Population.agents`' plain iteration order. Now every eligible sender
in the target settlement is collected (still each sender's own first
qualifying recipient, unchanged), then `humans_pillar.subject_
confidence(sender.name)` picks among them via `max` — first-max-wins
means no lean anywhere reproduces the exact prior first-found pick.

Verified: a production-path test through the real `_maybe_schedule_
letter` (a synthetic two-sender scenario — no-lean picks the original
first-found sender, a seeded belief flips it), a 4000-tick LLM-
disabled soak with clean round-trip, `pyflakes` clean. Tier 0 now has
fifteen real converted sites.

## Current state (v1.34.109)

Explicit user instruction: "Continue tier 0." Fourteenth conversion, a
self-referential site (same shape as `ontology_evolution`'s Innovation
self-lean): `_maybe_schedule_personal_belief` writes `humans_pillar.
world_model` but its own monthly candidate draw (`rng.sample`, uniform
without replacement) never read it. Converted to a sequential weighted
draw without replacement using the same `HUMANS_PERSONAL_TARGET_LEAN_
WEIGHT` every sibling Humans-lean site already uses. Preserves the
DISTRIBUTION with no lean (verified statistically) even though the
RNG-consumption pattern itself changes (documented, same acknowledged
class as prior `rng.choice`->`rng.choices` conversions).

Verified: a 20,000-trial statistical test (uniform baseline, seeded-
lean bump), a production-path test through the real scheduling
function (forced gate, seeded belief raises pick rate), a 6,000-trial
no-lean production-path regression test, a 4000-tick LLM-disabled soak
with clean round-trip, `pyflakes` clean. Tier 0 now has fourteen real
converted sites.

## Current state (v1.34.108)

Explicit user instruction: "Continue." Thirteenth Tier 0 conversion,
found by re-auditing existing call sites rather than a new content
design — `_voice_narrative_extra_scores` (feeds `Population.select_
voice_pair`'s "who's the weekly protagonist" ranking, alongside a
recent-inventor and active-COUNCIL bonus) now also folds in `humans_
pillar.subject_confidence(agent.name)` for the core cast, reusing the
same proven per-agent-name-keyed content five prior sites already
established. New `VOICE_NARRATIVE_HUMANS_LEAN_MAX = 2000.0` keeps it
below the inventor (4000)/council (3500) bonuses — a standing Humans
theory nudges the pick, never overrides a genuinely dramatic event.

Verified: a direct test of the score computation (no-lean baseline,
exact seeded-confidence bump, non-core agents unaffected), a
production-path test through the real `select_voice_pair` (a seeded
max-confidence belief flips the protagonist to a different core-cast
member), a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean. Tier 0 now has thirteen real converted sites.

## Current state (v1.34.107)

Explicit user instruction, following v1.34.106's `AskUserQuestion`:
"Species-keyed theory producer (Recommended)." Twelfth Tier 0
conversion, Nature pillar's first-ever site. New deterministic mirror
inside `_maybe_schedule_nature_mind`'s apply(): whenever the job's own
already-computed `wildlife_summary` shows real pressure (`prey_
scarce`, or `predator_pressure_ratio > 0.25`), it also upserts a
second `nature_pillar.world_model` entry keyed by the literal species
word (`"grazer"`/`"predator"`) — computed from Body state, not the
LLM's free text, so it's a reliable subject unlike Nature's ordinary
belief content. Revised in place via `find_world_model_entry` so
repeated firings don't pile up near-duplicates.

Real consumer: `_maybe_schedule_species_variant`'s herd pick
(previously flatly lowest-id) now sorts by `nature_pillar.subject_
confidence(herd.species.value)` descending, lowest id as the
tiebreak — a species Nature has lately been "worried about" is now
measurably more likely to get a named variant next. No lean anywhere
(the common case) reproduces the exact prior lowest-id pick.

Verified: direct tests of the producer (writes/revises in place) and
consumer ordering, production-path tests through the real `_maybe_
schedule_nature_mind`/`_maybe_schedule_species_variant` (forced
pressure signals; a seeded predator lean flips the pick to the
higher-id predator herd), a no-lean regression test, a 4000-tick
LLM-disabled soak with clean round-trip, `pyflakes` clean. Tier 0 now
has twelve real converted sites.

## Current state (v1.34.106)

Explicit user instruction: "Invent new content ask me if needed and
continue tier 0." Eleventh conversion, Reflection pillar's first-ever
Tier 0 site — needed no invented content, unlike Nature (see below):
`_detect_reflection_pattern`'s subjects are already settlement-name-
keyed, so its own multi-settlement-crosses-threshold-same-cycle
tiebreak was a real, immediately usable site. Settlements are now
checked in order of `reflection_pillar.subject_confidence(settlement.
name)` (descending) before the existing per-settlement threshold scan
— "the settlement Reflection already has a standing theory about" is
examined first; `list.sort`'s stability reproduces the exact prior
list-order result when no lean exists anywhere.

Nature pillar investigated and found genuinely blocked — its real
`world_model` content (free-text ecological phrases, fixed hypothesis
strings) doesn't reliably match any existing WHICH-candidate site,
the same fragile-dead-end shape Humans hit before v1.34.98's real
producer. Asked via `AskUserQuestion` rather than forcing a decorative
site; user chose "species-keyed theory producer" — a new mechanism
where Nature mirrors a belief keyed by literal species type
("grazer"/"predator"), consumed by `_maybe_schedule_species_variant`'s
currently flat-lowest-id herd pick. Not yet built — next up.

Verified: a direct production-path test (two settlements forced to
cross the same threshold the same cycle, no-lean vs. seeded-lean
cases), a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean. Tier 0 now has eleven real converted sites.

## Current state (v1.34.105)

Explicit user instruction: "Continue Tier 0." Tenth conversion:
`_maybe_schedule_dream`'s monthly dreamer pick had the same WHICH-
candidate shape as `memory_drift`/`noncore_nudge` — reused the same
`HUMANS_PERSONAL_TARGET_LEAN_WEIGHT` (no reason to tune a fourth
Humans site differently). The person Humans' own attention already
returns to is now measurably more likely to be this month's dreamer.

Verified: a production-path test through the real `_maybe_schedule_
dream` (forced gates, max-weight fake RNG, confirmed the favored
agent's name appears in the built prompt), a 4000-tick soak with
clean round-trip. Ten real Tier 0 sites converted.

## Current state (v1.34.104)

Explicit user instruction: "Check A12 why it is shown as not done and
progress through tier 0."

A12: per-building-instance material shipped v1.34.58; the checklist
stays unchecked because the item's literal scope (generalizing beyond
buildings, e.g. `Vehicle`) is still genuinely unbuilt — correctly so,
since no real consumer exists for a vehicle's material yet and
inventing one just to close the box would violate the standing
"mechanically real, not a stub" discipline. Not a bug.

Tier 0's eighth/ninth conversions: `_maybe_schedule_invention`/
`_maybe_schedule_ontology_proposal`'s inventor-selection sites (same
WHICH-candidate `rng.choice` shape as the fifth/sixth/seventh sites)
now weight by `humans_pillar.subject_confidence(agent.name)` via new
`INVENTOR_HUMANS_LEAN_WEIGHT=0.4` — the community's own notable person
becomes measurably more likely to be credited as an invention's
inventor. Nine real Tier 0 sites now converted.

Verified: a direct statistical weighting test (3000 trials), a
production-path test through the real `_maybe_schedule_invention`
confirming the favored agent becomes the recorded knower, a 4000-tick
soak with clean round-trip.

## Current state (v1.34.103)

Explicit user instruction: "Let's complete tier 2 first." Tier 2 turned
out already fully closed (every item CLOSED, nothing open). Via
`AskUserQuestion`, moved to Tier 3's open items: C2 (large, mostly
blocked on Tier 0's own unfinished refactor — left flagged) and C3
("pillars may initiate contact," shipped).

New `Pillar.initiated_messages`/`push_initiated_message`: the pillar-
to-player direction the existing `conversation_log` (player-initiated
Q&A) doesn't cover. Zero new LLM cost — always surfaces an already-
formed `world_model` belief, never generates fresh text. New
`SimulationEngine._maybe_pillar_initiates_contact` (monthly): a
pillar's newest belief crossing a real confidence threshold gets a
real monthly roll to volunteer it, deduped by entry id. `GET /pillar/
{pillar}` and the "ask a pillar" main-UI panel both surface it.

Verified: direct unit tests (cap, round-trip, legacy backfill), a
production-path test through the real scheduling function (fires
once, no duplicate, no-op off month_end, no-op below confidence), a
4000-tick soak with clean round-trip. No native module touched.

## Current state (v1.34.102)

Explicit user instruction: "Can we build some from tier 5?" — starts
Tier 5 (docs/HEARTHBENCH-RUNTIME-2026-07-23.md) ahead of its own
"sequenced strictly after Tiers 0-4" note, a genuine user decision.
Via `AskUserQuestion`, picked B15.1 (replay-hash equivalence test)
over HearthBench's A1 skeleton or the C5 model passport — the doc's
own first-recommended Runtime item, "the safety net every later
[runtime] change leans on."

New `scripts/verify_replay_hash.py`: mechanical proof that the same
seed with the LLM disabled produces byte-identical `World.to_dict()`
state across two fully independent PROCESS runs (subprocess isolation
by default, matching the real "different run/machine" claim B15.1
makes) — mirrors `scripts/verify_native_soak.py`'s structure but
compares two independent runs of the same code path rather than
native-vs-fallback. Confirmed MATCH at 400 and 3000 ticks. Nothing
else in Part B (task scheduling, budgets, dormancy) exists yet — this
is the floor those features will be checked against once they do.
Both Tier 5 tracks otherwise remain unstarted.

## Current state (v1.34.101)

Explicit user instruction: "Continue A16." Ships A16's last piece,
trade-as-network-flow — **A16 is now fully closed** (tech-as-DAG
v1.34.99, information-propagation v1.34.100, this).

`Settlement.relations` was already a real weighted inter-settlement
graph, but every prior consumer only read a flat average across it.
New `world/graph_algorithms.py`'s `build_settlement_trade_graph`/
`max_flow` (a real Edmonds-Karp max-flow) are consumed by new
`SimulationEngine._maybe_tick_settlement_trade` (monthly,
deterministic, zero LLM cost): the settlement in the deepest materials
surplus supplies the one in the deepest deficit, routed through the
real relations graph — a settlement can now supply another it's
directly HOSTILE toward, via a third settlement both are warm toward,
the genuinely distinct case a flat pairwise multiplier can't express.
No new UI surface — reuses the existing "caravan" event category.

Verified: direct unit tests of both new graph functions (including
the multi-hop routing case), a production-path test through the real
`_maybe_tick_settlement_trade` (hostile source/sink routed via a warm
third settlement, confirming genuine flow occurred and the router's
own materials stayed untouched), edge-case tests, a 4000-tick
LLM-disabled soak with clean round-trip. No native module touched.

## Current state (v1.34.100)

Explicit user instruction: "Continue A16." Ships A16's second
remaining piece (tech-as-DAG shipped last pass, v1.34.99):
information-propagation-as-graph-algorithm.

`Population.spread_rumor` (a caravan's outside news) previously drew
every listener via pure `rng.sample` over the whole living population
— no regard for social closeness, despite its own docstring claiming
the news propagates through existing gossip contagion. New `world/
graph_algorithms.py`'s `bfs_distances` (real BFS over the relationship
graph, positive-weight edges only) now backs a distance-weighted draw
for every listener after the first (a genuine uniform point of
contact): closer is more likely, with a real baseline floor so a
stranger can still occasionally hear it.

**A16 is now closed on two of its three pieces** — trade-as-network-
flow remains open, a larger lift with no existing inter-settlement
goods-flow mechanic to build over yet.

Verified: direct unit tests of `bfs_distances`, a production-path
statistical test through the real `spread_rumor` (friend clique vs.
strangers, 82% vs. 58% inclusion over 3000 trials), edge-case tests,
a 4000-tick LLM-disabled soak with clean round-trip. No native module
touched.

## Current state (v1.34.99)

Explicit user instruction: "Start A12." Investigation (docs/ROADMAP-
2026-07-REMAINING.md) found A12 as literally scoped (per-instance
`Entity.material` generalized beyond `Building`) was already audited
(v1.34.67) and correctly left unattempted — no real consumer exists
for a `Vehicle`'s material, and inventing one would violate the
standing "mechanically real, not a stub" discipline. Moved to A16, a
genuinely open item with a concrete unbuilt piece.

`InventedConcept.lineage` has been a real DAG since v1.3.19, but no
genuine graph traversal had ever run over it. New `world/graph_
algorithms.py`'s `ancestor_ids`/`shares_lineage` (transitive-closure
walk up the DAG, cycle-guarded) are A16's "tech-as-DAG" piece. Real
consumer: `_maybe_schedule_ontology_evolution`'s merge-pair selection
now rejects a pair that already shares lineage (bounded 4 retries,
then merges the original pair rather than silently no-op'ing) —
previously nothing stopped a concept from being merged with its own
parent or sibling. Trade-as-network-flow and information-propagation-
as-graph-algorithm (A16's other two pieces) remain open — larger
lifts, no existing flow/contagion graph structure to build over yet.

Verified: direct unit tests of both new functions over a hand-built
5-concept lineage, a production-path test through the real
`_maybe_schedule_ontology_evolution` (forced-merge RNG + seeded
sibling pair, confirming the scheduled prompt names the unrelated pair
instead), a 4000-tick LLM-disabled soak with clean round-trip. No
native module touched.

## Current state (v1.34.94)

Explicit user instruction: "Complete and finish A10 with all remaining
items." Closes the field-substrate fold-in's last flagged gap: `scent`
(predator presence) had exactly one consumer, the human-side fission-
site avoidance — no wildlife-side field folded predator danger back
into GRAZER behavior at region scale. New `SCENT_REGIONAL_AVOIDANCE_
MAX=0.4`: `WildlifeGrid.tick`'s GRAZER move-candidate weighting now
also avoids high-`scent` regions, layered on top of (not replacing)
the existing hard-radius local flee response — a softer, region-scale
"bad stretch of country" sense beyond the flee radius's hard cutoff.
`scent=None` reproduces the exact prior behavior byte-for-byte.

**A10 is now fully closed** — all five named det_sys.md pieces plus
the field-substrate fold-in (both directions of `population_density`/
`wildlife`, plus `scent`'s reciprocal consumer) are real, verified,
shipped mechanics.

Verified: a direct parity test, a direct weight-formula statistical
test (20,000 trials), a production-path statistical test through the
real `WildlifeGrid.tick()` on synthetic terrain (0.169 vs. 0.244
crossing rate into a scent-flagged region over 3000 trials), a
4000-tick soak with clean round-trip, `pyflakes` clean. No native
module touched.

## Current state (v1.34.93)

Explicit user instruction: "Continue A10." Second field-substrate
fold-in slice, closing the other direction of the bidirectional
coupling v1.34.92 started (wildlife reading a human-written field) —
this one makes humans read a wildlife-written field back. New
`FieldGrid.step_wildlife` sums live GRAZER-herd presence per region
(the deliberate positive counterpart to `scent`'s predator-danger
signal), wired into `World.tick()`. Real consumer: `Population.
_maybe_welcome_migrant` gained `MIGRANT_WILDLIFE_PULL=0.2` — a fifth
positive region-field pull, "word travels that a place has good
hunting," `None` a genuine no-op. UI: new "wildlife" (game presence)
overlay mode + legend; both `WorldBroadcaster.set_terrain` call sites
in `simulation/engine.py` updated together (the project's own
standing "one call site missing a field" bug class).

Verified: direct unit tests for `step_wildlife`, a production-path
`World.tick()` test confirming organic field formation from real
grazer herds, a legacy-backfill test, a 4000-tick soak with clean
round-trip, a direct broadcaster-payload test (present + omitted-kwarg
parity), `node --check`/`pyflakes` clean. No native module touched.

## Current state (v1.34.92)

Explicit user instruction: "Continue A10." All five named det_sys.md
pieces already shipped (v1.34.87-.91) — this ships a real first slice
of the remaining, explicitly-larger "fold the food web onto A1's
field substrate" item rather than attempting it whole. Audited every
wildlife-side field consumer (`nutrients`/`scent`/`noise`) and found
none read a field the human/settlement side writes — `population_
density` (A1's own first field) had zero wildlife-side consumer.
`WildlifeGrid.tick`'s move-candidate weighting now also avoids
heavily populated regions (`WILDLIFE_POPULATION_AVOIDANCE_MAX=0.6`,
floored, combined multiplicatively with trail/nutrient terms) —
"wildlife shies from busy human areas," the first genuine
bidirectional link between the ecology and settlement field halves
(humans already read a wildlife-adjacent field, `scent`, back).
`population_density=None` reproduces the exact prior RNG-consumption
pattern byte-for-byte, verified directly.

Verified: a direct parity test, a weight-floor check, a production-
path statistical test on a 60x60 map with a real population-density
gradient (herds avoided the crowded region markedly more often — 2/40
vs. 6/40 seeds — than a no-pressure control), a 4000-tick soak with
clean round-trip. No native module touched. The rest of the field-
substrate fold-in (a wildlife-presence field of its own, etc.) remains
open — explicitly a first slice, not closure.

## Current state (v1.34.91)

Explicit user instruction: "Continue A10." Ships migration — the
last of A10's five named pieces. `WildlifeGrid.tick`'s existing move-
candidate weighting (previously only M4's trail-reuse preference) now
also weights toward candidate tiles with a richer `nutrients` reading
(`MIGRATION_NUTRIENT_PULL_WEIGHT=2.0`), combined multiplicatively
with trail preference when both apply. `nutrients=None` reproduces
the exact prior RNG-consumption pattern byte-for-byte, verified
directly.

Verified: a direct parity test (500-tick identical trajectories with
both params omitted vs. explicit `None`), a weight-formula check, a
production-path statistical test on a 60x60 map with a real nutrient
gradient (herds ended up in the rich region more than twice as often
as a no-pull control across 40 seeds each), a 4000-tick soak with
clean round-trip. No native module touched.

**A10 is now closed on every named det_sys.md piece** (migration,
competition, decomposition, pollination, habitat formation) — only
folding the whole food web onto A1's field substrate remains, a
larger unscoped follow-up.

## Current state (v1.34.90)

Explicit user instruction: "Continue A10." Ships habitat formation —
det_sys.md's "reads fields, writes carrying capacity" — the one A10
axis with no prior implementation at all. New `world/wildlife.py`'s
`habitat_capacity(nutrients_at, base=MAX_HERD_SIZE)`: the same
`nutrients` field `NUTRIENTS_REPRODUCE_BONUS_MAX` already reads for
reproduce chance now also raises how large a herd its region can
sustain, up to 50% past the flat baseline in a nutrient-rich region.
Pure bonus, never a penalty — `nutrients_at=0` reproduces the exact
flat `MAX_HERD_SIZE` cap byte-for-byte (verified directly), matching
this module's "field absence means neutral" discipline. Wired at both
the native fast path's cap argument and the pure-Python fallback's
cap check via one shared `effective_max_herd_size`.

Verified: direct unit tests (zero-parity, full-bonus value,
monotonicity, floor), a production-path test through the real
`WildlifeGrid.tick()` (a herd at the flat cap genuinely grows past it
in a nutrient-rich region; a no-nutrients control confirmed it never
exceeds the flat cap), a 4000-tick soak with clean round-trip. No
native module touched.

## Current state (v1.34.89)

Explicit user instruction: "Continue A10." Ships the competition
slice, following decomposition (v1.34.87) and pollination (v1.34.88).
Multiple live GRAZER herds sharing a tile now genuinely compete for
the same limited forage — `WildlifeGrid.tick`'s new `grazer_tile_
counts` aggregate (same cheap-up-front-O(n) discipline as the
existing trophic-pressure reads) feeds a `competition_factor` into
each herd's `reproduce_chance` (`COMPETITION_PENALTY_PER_RIVAL=0.15`
per rival, floored at `COMPETITION_MIN_REPRODUCE_FACTOR=0.4`). A herd
alone on its tile — the common case — sees `competition_factor`
exactly `1.0`, verified as a genuine no-op. Folds into the same float
both the native fast path and pure-Python fallback already share, so
no native-module change was needed.

Real bug caught and fixed during implementation: the rival lookup
initially keyed off a herd's POST-movement position while the
aggregate itself was built pre-movement — a mismatched snapshot.
Fixed by capturing `pre_move_pos` before movement runs.

Verified: direct unit tests (formula bounds, floor, solo-herd no-op),
a production-path test through the real `WildlifeGrid.tick()` (frozen
movement to isolate the effect — solo herds averaged ~3x the growth
of 4-rival-crowded herds over 60 seeds), a 4000-tick soak with clean
round-trip. No native module touched.

## Current state (v1.34.88)

Explicit user instruction: "Continue A10." Ships the pollination
slice — det_sys.md's "pollination (→ vegetation)" line. Extended the
existing A2 succession-pressure mechanism (`terrain_evolution.compute_
succession_pressure`) with an optional `grazer_positions` param: a
live GRAZER herd's tile diffuses outward (same `ca_operators.diffuse`
composition `forest_density` already uses) and adds a genuine, capped
bonus to nearby succession pressure — "animals carry seeds and pollen
as they move." Threaded through `maybe_reclaim` to `World._tick_
terrain`'s call site.

Real bug caught and fixed during this slice's own verification (not
by the user): the first implementation blended pollination in as a
weighted average, which silently LOWERED succession pressure on every
wildlife-free tile (since "no wildlife" reads as 0, diluting the base
reading by the blend weight everywhere, not just adding a bonus where
wildlife is present). A direct "far tile should be unaffected" test
caught it immediately; fixed to a straightforward additive+capped
bonus, re-verified a wildlife-free tile now reads byte-identical to
before this param existed.

Verified: direct unit tests (no-grazer parity, real bump near a herd
with a confirmed-unaffected far tile, bounds, `moisture=None`
untouched), a production-path test through the real `World.tick()`
with genuine grazer herds present, a 4000-tick soak with clean round-
trip. No native module touched.

## Current state (v1.34.87)

Explicit user instruction: "Check for other performance implications
and fix them. Start A10 after that." Performance re-audit: grepped
every `_tick_once()` call site codebase-wide — confirmed sandbox.py's
two loops (fixed v1.34.86) were the only instance of the "synchronous
multi-tick loop inside an async function" bug class; nothing else
found.

A10 "Ecology / food webs," decomposition slice: a real carcass from a
successful predator kill is a distinct, discrete nutrient source from
the already-shipped live-herd `apply_nutrient_cycling` (an ongoing
per-tick dung trickle). New `World.carcass_decomposition` (same scar-
shaped-dict pattern as `migration_trails`/`road_scars`) gained via
`WildlifeGrid.tick`'s real kill site (`terrain_evolution.apply_
carcass_decomposition`, `None`-default reproduces prior behavior
byte-for-byte — verified), decays weekly (~5 weeks to clear, faster
than migration trails since a carcass rots quicker than a habit
fades), consumed by `economy.farms.apply_carcass_decomposition_bonus`
— a real, stronger-than-live-grazing soil-fertility bump near a kill
site. UI: new map overlay color, main-UI stat tile, bare-tile
inspector line; both `set_terrain` call sites updated together
(v1.34.75's "one call site missing a field" bug class, checked
deliberately this time).

Verified: direct unit tests for all three new functions, a
production-path test through the real `WildlifeGrid.tick()` (forced
kill, confirmed decomposition forms; `None`-vs-omitted RNG/behavior
parity), a 4000-tick engine soak with clean round-trip + legacy
backfill, and a live dev server + `curl` pass confirming the field
reaches both `/terrain` and `/state`.

## Current state (v1.34.86)

Direct user follow-up question on v1.34.85: "Would this worsen the
back pressure drop or slow the simulation down? The forking." Measured
rather than guessed — found `evaluate_concept_dual_fork`'s (and the
pre-existing `run_counterfactual`'s) inner tick loop had no `await`
inside it; at ~12ms/tick this meant ~3.5 real seconds where the dual-
fork's two 150-tick forks fully froze the real event loop (tick loop,
LLM I/O completion, WebSocket broadcasts) each time a concept
retirement fired the check — not a backpressure-counter effect (LLM
disabled inside the fork), but a real live-simulation stall. Fixed
with one `await asyncio.sleep(0)` per tick in both loops — same wall-
clock cost, but the real engine can now interleave instead of freezing.
Verified via a direct concurrency test proving real interleaving now
happens, plus a clean 4000-tick soak and the existing unit tests.

## Current state (v1.34.85)

Explicit user instruction: "Take dual fork of A8" — the heavier
comparative mechanism v1.34.84's investigation flagged as the only
way to make A8's "sandbox forward-simulation as a fitness input" ask
genuinely meaningful, rather than the naive acceptance-gate approach
that pass correctly declined to ship as a vacuous rubber stamp
(`InventedConcept.mechanical_hook` is never consumed).

Before building on it, re-confirmed that finding wasn't a blanket
"adoption has zero effect" — `adopter_ids` (distinct from
`mechanical_hook`) DOES causally shape simulation dynamics via
`FieldGrid.step_cultural_influence` -> `Population._maybe_welcome_
migrant`'s `MIGRANT_CULTURAL_PULL` (v1.34.62). New `simulation/
sandbox.py`'s `evaluate_concept_dual_fork`: forks the world twice
from one shared snapshot (with vs. without a concept's real
`adopter_ids`, both LLM-disabled, 150 ticks) and returns the
population delta — meaningful rather than noise because both forks
share the identical seed/RNG stream, so a nonzero delta is a real
migrant-threshold tipping point, not independent sampling variance.
New `world/ontology.py`'s `reinstate_concept` is a SECOND, slower
causal opinion layered on top of (never replacing) `run_selection`'s
existing immediate correlational retirement — `SimulationEngine.
_confirm_concept_retirement` diffs retired-concept-ids before/after
each `run_selection` call and schedules an async dual-fork check per
newly-retired concept; a positive delta reinstates (status back to
`established`, `fitness_history` cleared, the mirrored Innovation
belief re-confirmed), zero/negative leaves the retirement standing.
UI: new `ontology_reinstated` event (♻️).

Verified: direct unit tests (`evaluate_concept_dual_fork`'s no-
adopters/nonexistent-concept `None` cases, a real with-adopters fork
pair, non-mutation of the real world; `reinstate_concept`'s non-
retired no-op and real-retirement reinstatement), a production-path
test through the real `_confirm_concept_retirement` background-task
wiring (positive delta reinstates, negative stays retired), a direct
test of the real `run_selection` retired-diff detection, a 4000-tick
LLM-disabled soak with clean round-trip. No native module touched.

## Current state (v1.34.84)

Explicit user instruction: "Start A7 and A8" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 3). A7's layout domain closed: unlike dialect
(recursive `steps`) and architecture (per-instance descriptor), layout
was a flat `settlement_id % 3` hash with zero lineage awareness. New
`Settlement.layout_style` (persisted, `None` = fall back to the
original hash — zero migration) + `layout_grammar.drift_layout_style`
(a real one-generation production rule, ~2:1 stay-vs-rewrite-to-next-
style-in-cycle) wired at fission: a daughter's style now genuinely
descends from its parent's, so a lineage several fissions deep can end
up visibly further from its founding settlement's tradition. All three
existing consumers (build-site scoring, the "Layout" stat tile,
building-descriptor diagnostics) now read `effective_layout_style`.

A8 investigated, not shipped: wiring the existing sandbox as an
ontology-proposal acceptance gate (mirroring TriggerRule/
CompositeReaction) would be real code but a vacuous signal —
`InventedConcept.mechanical_hook` is never actually applied to World
state, and even the one hook type anywhere in the codebase that IS a
real numeric effect (`belief_confidence_bonus`) can't plausibly trip
the sandbox's population/materials invariants. Shipping it would be a
rubber stamp, not a real check. A genuinely meaningful version needs a
comparative dual-fork (with vs. without a concept's adoption) — a
materially larger lift, flagged rather than forced through.

Verified (A7 only): direct unit tests (drift ratio, cycle wrap,
invalid-style fallback), round-trip tests (real value, `None`
fallback, legacy-snapshot backfill), a direct fission-site-shape test,
`pyflakes` clean, a 4000-tick soak with clean round-trip.

## Current state (v1.34.83)

Explicit user directive: "I am okay with occasional slow world
progression so do that" — accepting the pacing tradeoff flagged after
v1.34.81/.82's structural backpressure-drop fixes. `LLM_PRESSURE_
SLOWDOWN_START_RATIO` lowered 0.75 -> 0.5: at low integer concurrency
(`llm_max_concurrent=1` gives limit 3), `llm_pressure_ratio()` only
takes values `k/3`, and 0.75 sat strictly between 0.67 (backlog 2 —
already effectively saturated for a single-slot server) and 1.0
(backlog 3 — the exact point drops start), so a backlog of 2 engaged
no slowdown at all. 0.5 makes backlog=2 engage real pacing (~1.56x
tick-gap stretch, verified) before the queue is completely full,
trading world-progression speed under sustained pressure for fewer
wasted attempts — the explicit tradeoff requested. Speedup band and
the "just right" zone (now 0.15-0.5) otherwise unchanged.

Verified: a direct check of the interval-multiplier curve across the
concurrency=1 backlog range, `pyflakes` clean, a 4000-tick soak with
clean round-trip. Pure constant/docstring change.

## Current state (v1.34.82)

Explicit user follow-up: "Any more things we can do to reduce
backpressure drop [rate]?" — looked for the same bug class v1.34.81
fixed at other call sites. Found `_season_year_gate` (backing
`SEASON_YEAR_JOBS_WITH_RETRY`'s 9 jobs — tradition/religion/
narrative_direction/culture_digest/documentary/institution_culture/
invention/ontology_proposal/ontology_evolution) had the identical gap:
unlike `_monthly_gate`, which correctly restricts its retry window to
`"day_end"` ticks only, `_season_year_gate`'s retry window returned
True on literally every tick for up to `SEASON_YEAR_JOB_RETRY_WINDOW_
DAYS` (5) days, re-incrementing `calls_dropped_backpressure` on every
one of those ticks while still saturated. Fixed by requiring
`"day_end" in events` inside the window, matching `_monthly_gate` —
free on the window's own opening tick (a season/year boundary is
always also a day boundary by construction), only the subsequent
every-tick re-checks are now once-a-day.

Verified: a direct unit test against a real engine/world (opening tick
still True, a non-day_end tick inside the window now False where it
used to be True, the next real day_end tick inside the window still
retries), `pyflakes` clean, a 4000-tick soak with clean round-trip.

## Current state (v1.34.81)

Explicit user follow-up on v1.34.80's diagnostic fix: "check [pacing
constant reachability] first, and do whatever you can to fix the
[backpressure] drop rate without reducing simulation quality." The
pacing mechanism itself was reachable and correct; the real cause was
`_maybe_schedule_nature_causal_reasoning`'s three triggers (predator/
grazer extinction, succession stall) — unlike every other LLM job,
these are checked UNCONDITIONALLY every tick while their anomaly
persists, so the same still-saturated queue got counted as a fresh
drop on every single tick for thousands of consecutive ticks (that
run's `nature_causal_reasoning` succeeded only 6 times total against
a large share of the 10022 drops). New `SimulationEngine._reactive_
pillar_backpressured(pillar, trigger_key)` backs a rejected trigger
off for `REACTIVE_TRIGGER_BACKPRESSURE_RETRY_TICKS=50` ticks before
re-checking (and re-counting) — the cheap anomaly-detection stays
unconditional every tick, only the expensive/counted backpressure
check is throttled, so this costs at most a negligible delay before
the eventual real call, never changes what gets scheduled or narrated.
Also checked, per the request to move low-priority calls to
deterministic systems: no further clear candidate found — the other
high-volume jobs (`cognition`/`voice_dialogue`/`record`/`musing`) are
each already gated and are deliberately LLM-authored texture per this
project's own priority order, not a "decision + narration" shape the
v1.3.35 batch's conversions apply to.

Verified: a direct unit test against a real `SimulationEngine`
(backoff suppresses repeat increments, a fresh check after the window
elapses re-attempts, clearing pressure returns cleanly), `pyflakes`
clean, a 4000-tick LLM-disabled soak with clean round-trip.

## Current state (v1.34.80)

Explicit user request: diagnose a real 40k-tick live LLM-enabled run
(pasted `/diagnostics`, `hearthmind_version` "1.34.69" — an older
deployment) and fix bugs found. Real bug: `nature_pillar.world_model`/
`reflection_pillar.world_model` accumulated near-duplicate entries for
the SAME recurring subject (e.g. "the vanished predator packs"
re-hypothesized 5 times, a repeated consciousness intervention
appended 9 times) instead of revising in place — `nature_causal_
reasoning`'s three reactive triggers and `consciousness`'s Reflection
mirror all call `upsert_world_model` with no `revises_id`, and unlike
every other belief-forming job (which gets a revision target from the
LLM's own `revises` field) these four have no such field, so a
same-subject re-firing always appended fresh. New `Pillar.find_world_
model_entry(subject)` (exact-match lookup, distinct from `disagrees_
with`'s fuzzy one) wired at all four sites — a recurring anomaly now
updates one evolving belief instead of piling up near-copies. No other
clear bug found; the report's large `calls_dropped_backpressure`
reflects that deployment's own `llm_max_concurrent=1` choice, not a
defect, and the pillar world_model mixing both settlements' history is
expected (pillars are world-scoped singletons by design).

Verified: direct unit tests (revise-in-place, distinct-subject-still-
appends, case-insensitive match, no-match), `pyflakes` clean, a
4000-tick LLM-disabled soak with clean round-trip. Pure Python, no
native soak needed for this slice.

## Current state (v1.34.79)

Explicit user instruction: "Do the native module change and ask me
when in doubt" — the one A5/A6 piece v1.34.78 explicitly flagged and
left unattempted: `Settlement.tick`'s decay loop has a native fast
path (`_native_building_decay_tick`) that took one flat scalar decay
rate for the whole batch, so `material_repair_factor`'s real-material
sensitivity had no decay-side equivalent without a genuine native-
module signature change. No ambiguity arose worth asking about.

`cpp/src/settlement_decay.cpp`'s `building_decay_tick` input tuple
gained a 5th field, `material_decay_factor`, multiplied directly into
the existing `hut_decay`/`civic_decay` scalar. The factor is computed
in Python at `World.tick`'s call site (`world/state.py` — the layer
that already imports both `settlement.buildings` and `world.materials`
without a cycle, since `materials.py` imports `BuildingKind` FROM
`buildings.py`), same "compute where both dependencies meet" shape
`nature_adaptation_bias` uses. New `world/materials.py`'s `material_
decay_factor(name)` mirrors `material_repair_factor`'s shape exactly
but reads `Material.decay_rate` instead of `workability` — stone/ore/
ceramic now weather at ~0.55-0.7x the old flat rate, wood/fiber at
~1.0-1.2x. `Settlement.tick` gained an optional `material_decay_
factors: dict[int, float] | None` param threaded through both the
native call site and the pure-Python fallback loop identically; `None`
reproduces the exact pre-A5/A6 flat rate on both paths. No new UI
needed — the existing "Built of" repair-speed suffix already implies
the same material's decay-speed reading. **A5/A6 is now fully
closed.**

Verified: the native extension was rebuilt and confirmed to accept the
new 5-tuple; direct `material_decay_factor` unit checks confirming
correct ordering across every material; a production-path test
through the real native-backed `Settlement.tick()` (fiber vs. stone,
50 ticks, confirming genuinely differential decay, plus a `None`-path
regression check); a 4000-tick soak with clean round-trip (no new
persisted state); `scripts/verify_native_soak.py` (3 seeds x 3000
ticks) confirming native and fallback produce byte-identical `World.
to_dict()` output every tick — the load-bearing check for this native-
module signature change.

## Current state (v1.34.78)

Explicit user instruction: "Start A5/A6" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 3). The affordances half was already closed
(`world/materials.py`'s `building_instance_affordances`, A13,
v1.34.58) — this ships the other named half, `Entity.properties`,
which had zero real consumer until now.

New `world/materials.py`'s `material_repair_factor(name)`: a
material's `workability` scales `Population._maybe_repair`'s repair
rate — wood/fiber/clay repair meaningfully faster than stone/ore/
ceramic, reading `effective_material_name(building)` (A13's existing
per-instance resolution point) so a chemically-converted building's
real new material changes its own repair speed. Decay itself was
deliberately left untouched — the native fast path
(`_native_building_decay_tick`) takes one shared scalar for the whole
batch; correctly per-instance-izing it needs a real native-module
change, flagged as a bigger follow-up, not attempted. Repair is pure
Python (agent-mediated, never native-backed), zero parity risk. UI:
the "Built of" inspector line gained a plain-language repair-speed
suffix.

Verified: direct unit tests, a production-path test through the real
`_maybe_repair` (ceramic vs. fiber building, confirming genuinely
different repair speed), a 4000-tick soak with clean round-trip,
`scripts/verify_native_soak.py` (3 seeds x 3000 ticks) byte-identical,
a live dev server + Playwright pass.

## Current state (v1.34.77)

Explicit user instruction: "A17", resolved via `AskUserQuestion` into
"both remaining pieces" (docs/ROADMAP-2026-07-REMAINING.md) — the two
items v1.34.59's audit found and explicitly flagged as needing a user
decision rather than an implementation judgment call.

Fitness-vs-truth axis for rumors: sidesteps the flagged risk (needing
a ground-truth value per rumor, cutting against Phase G's "belief
never has to reconcile with reality" principle) by never measuring
against objective reality — `world/memetics.py`'s `rumor_truth_score`
measures fidelity to what was ORIGINALLY SAID (via InterpretRumor()'s
retelling), never the state of the world; `rumor_fitness` is an
independent dramatic-keyword heuristic. Real consumer: `Population.
_apply_rumor_retelling_fitness` polarizes the reteller's own opinion
of whoever their retelling names, scaled by fitness alone — truth_score
is tracked (dev-console only) but plays no role in the nudge.

Shared decay/compete step: `world/memetics.py`'s `find_near_duplicate`
("compete")/`prune_aged_entries` ("decay") wired to the two previously-
flagged sites. `SettlementCulture.record_topic` merges near-duplicate
topic phrasings (makes the existing dominant-topic gate MORE accurate,
doesn't touch v0.87.35's tuned constants — the risk that had kept this
site flagged). `Settlement.lexicon`'s coinage site gets both a meaning-
level near-duplicate check and a genuine age-based decay, riding its
existing quarterly append call site.

Verified: direct unit tests for all four new memetics functions
(including an explicit fitness-vs-truth independence demonstration),
production-path tests, a full end-to-end test through the real
`_maybe_interpret_rumor` scheduling pipeline with a fake LLM adapter,
a 4000-tick LLM-disabled soak with clean round-trip, `scripts/verify_
native_soak.py` (3 seeds x 3000 ticks) byte-identical.

## Current state (v1.34.76)

Explicit user instruction: "Build M1/M9 and ask questions if stuck"
(docs/ROADMAP-2026-07-REMAINING.md's Tier 1.5). Closes Tier 1.5 "The
Living Map" entirely — "field boundaries" was the one residual named
example, flagged unbuilt twice before (v1.34.50/69) as a genuinely
larger UI-redesign lift. Turned out to be a small, self-contained
frontend-only slice: new `app.js` `drawFieldBoundaries` traces a thin
hedgerow line around the outer edge of every contiguous cluster of
`latest.farms` tiles (any farmed tile's neighbor NOT also farmed gets
a boundary segment on the shared edge) — the same edge-crossing
technique `drawFieldContour` already established for the moisture
threshold isoline, applied to a binary membership set instead of an
interpolated value. Zero new backend state or payload field. No
`AskUserQuestion` needed — the roadmap's own item description was
unambiguous enough to implement directly.

Verified: `node --check` clean, a live dev server + Playwright pass
(zoomed screenshot confirms a real isolated farm plot renders a
distinct boundary line around its fill). Pure frontend change, no
native soak needed.

## Current state (v1.34.75)

Explicit user instruction: "Build A2 and A1 migrate mining_scars/
disaster_scars/the 3x3 climate grid onto FieldGrid" (docs/ROADMAP-
2026-07-REMAINING.md). Full detail: CHANGELOG.md's [1.34.75] entry.

A2: `ca_operators.reaction_diffuse` (mass-conserving two-grid
exchange, zero real consumers since v1.14.0) gets its first —
`moisture <-> snowpack`, literally the same water liquid vs. frozen.
New `HydrologyField.snowpack`, `hydrology_field.tick_snowpack`
(weekly, freezes below `SNOWPACK_FREEZE_TEMP_C` / melts above it).
Real consumer: `WildlifeGrid.tick`'s GRAZER reproduce chance is
dampened under deep snow (`SNOWPACK_REPRODUCE_DAMPENING_MAX=0.3`) —
real winter forage scarcity. UI: "Soil moisture" stat tile gained a
conditional snowpack suffix.

A1 migration: scoped as "coarse region-scale `FieldGrid` companion
reading, not a replacement" — `World.mining_scars`/`disaster_scars`/
`weather_regions` all remain the source of truth for their existing
tile-precise/full-`WeatherState` consumers. Two new fields (14th/15th):
`hazard` (region-summed `disaster_scars`) and `storminess` (region
`precipitation`/`wind` from `weather_regions`, the "3x3 climate grid").
Real consumers: `_choose_fission_site` avoids a heavily hazard-scarred
region when an alternative exists; `_maybe_schedule_caravan` dampens
chance in a stormy region (`STORMINESS_CARAVAN_CHANCE_DAMPENING=0.4`,
the negative counterpart to `traffic`'s positive pull). **Bug found
and fixed while wiring this**: one of two `set_terrain(...)` call
sites had been missing `beauty=` entirely since v1.34.74 shipped — the
`beauty` overlay never refreshed on the weekly `week_end` resync every
sibling field relies on, only on `TERRAIN_CHANGING_CATEGORIES` events.
UI: `hazard`/`storminess` as the 16th/17th "🗺️ fields" overlay modes.

Verified: direct unit tests, a production-path test through the real
`World.tick()` (weather monkeypatched to force sustained freezing
temperatures — `World.tick()` recomputes weather every tick, so a
direct `weather.temperature_c` override is silently discarded)
confirming organic snowpack formation + clean round-trip, a 4000-tick
LLM-disabled soak with clean round-trip, `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical, and a live dev server +
Playwright pass confirming both new overlay modes render correctly.

## Current state (v1.34.74)

Explicit user instruction: "Ask the beauty phase of A1 and finish
it." `AskUserQuestion` on `beauty`'s mechanical meaning — explicit
user answer: "New subjective agent-vote signal" (over a deterministic
composite or skipping the field entirely). Ships that answer, closing
A1 entirely.

New `world/aesthetics.py`: `compute_aesthetic_appraisal` scores the
tile a voting agent stands on from real cues (water-adjacency, scenic
biome, neighborhood variety, mining/disaster scar penalties), nudged
by the voting agent's own `TRAIT_OPENNESS` — the genuinely subjective
half. `tick_aesthetic_votes` gives every agent a cheap per-tick roll
(`BEAUTY_APPRAISAL_CHANCE_PER_TICK=0.02`); a vote folds into
`World.aesthetic_appraisal`, a new persistent 3x3 per-region EMA — the
one `FieldGrid` field NOT sourced from a live re-read of already-real
state, seeded neutral (0.5) rather than the usual "absence means
zero." `FieldGrid.step_beauty` spreads it via `diffuse` same as every
sibling field. Real consumer: `Population._maybe_welcome_migrant`
gains a fourth positive region-field term, `MIGRANT_BEAUTY_PULL=0.2`.
13th "🗺️ fields" UI mode.

Verified: 5 direct unit tests, a production-path test through the
real `World.tick()` confirming organic formation, a clean round-trip,
a legacy-backfill test, a 4000-tick soak, `scripts/verify_native_
soak.py` byte-identical, and a live dev server + Playwright pass.

**A1 is now fully closed** — all thirteen named fields real, each
with a real consumer and a real map overlay.

## Current state (v1.34.73)

Explicit user instruction: "Continue A1." Shipped `fertility`, the
12th real `FieldGrid` field — `FieldGrid.step_fertility` averages
`FarmGrid.soil_fertility` per region (same already-bounded-average
shape `step_scarcity` established), spread via `ca_operators.diffuse`.
Deliberately NOT a duplicate of `world/spatial_memory.py`'s
`location_character` (a per-tile flavor read of the same underlying
dict) — the real consumer is region-scoped:
`SimulationEngine._choose_fission_site` prefers a fertile region over
a non-fertile one when a qualifying candidate exists
(`FERTILITY_FISSION_PREFER_THRESHOLD=0.4`, never a hard block, applied
after the existing density/scent filters). 12th "🗺️ fields" UI mode.

Verified: 2 direct unit tests, a production-path test through the real
`World.tick()` confirming organic formation + clean round-trip, a
30-trial deterministic consumer test (every draw landed in the forced
fertile region), a 4000-tick LLM-disabled soak with clean round-trip,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical,
and a live dev server + Playwright pass.

Remaining under A1: `beauty` and the mining_scars/disaster_scars/
climate-grid migration, both still deferred on the v1.34.72
recommended-default judgment (unanswered `AskUserQuestion`) — not
re-asked this pass since nothing changed.

## Current state (v1.34.72)

Explicit user instruction: "Continue A1 and ask questions if your are
stuck." `AskUserQuestion` was used on two genuinely open design
decisions carried from v1.34.71 (`beauty`'s mechanical meaning; attempt
vs. defer the mining_scars/disaster_scars/climate-grid `FieldGrid`
migration) — **both went unanswered**, so both proceeded on the
recommended-default judgment call stated at the time (skip `beauty`,
leave the migration deferred), not a user-confirmed decision; re-raise
either on a future pass rather than treating this as settled.

**Correction to v1.34.71's own record**: that entry's claim that
`cultural-influence` "has no real data source anywhere in this
codebase without inventing a new subjective-scoring mechanic from
scratch" was wrong — `world/ontology.py`'s `InventedConcept.
adopter_ids: set[int]` is real, already-tracked, already-capped state.
Shipped it: `FieldGrid.step_cultural_influence` (`world/fields.py`)
tallies every living agent who has adopted at least one invented
concept into their current tile's region (a live census, zero new
tracked state, same shape `step_population_density` established),
`World.tick()` computes the adopter-id union each tick. Real consumer:
`Population._maybe_welcome_migrant`'s fifth optional region-field term,
`region_cultural_influence` (`MIGRANT_CULTURAL_PULL=0.25`) — a third
POSITIVE pull ("word travels that a place has real ideas") alongside
`ownership`/`heat`'s siblings. Real-field count now 11, plus an 11th
"🗺️ fields" UI mode.

Verified: 2 direct unit tests, a production-path test through the real
`World.tick()` with forced adopters confirming organic formation + a
clean round-trip, a 4000-tick LLM-disabled soak with clean round-trip,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical,
and a live dev server + Playwright pass confirming the overlay cycles
correctly with a matching legend.

**Still does not close A1**: `fertility`-as-a-FieldGrid-aggregate and
`beauty` remain unbuilt (per the unanswered-question default above);
the mining_scars/disaster_scars/climate-grid migration remains
deferred (same reason).

## Current state (v1.34.71)

Explicit user instruction: "Finish building A1 this turn." Shipped
three more `FieldGrid` fields with real consumers — `heat` (region
`WeatherState.temperature_c`, dampens `Population._maybe_welcome_
migrant`'s chance in scorching regions), `nutrients` (region wild-FOOD
abundance, bonuses `WildlifeGrid` grazer reproduction), `scent`
(region live-predator-pack presence, steers `SimulationEngine._choose_
fission_site` away from dangerous regions when an alternative exists)
— bringing the real-field count to ten, plus 3 more "🗺️ fields" UI
modes (13 total). **Does not literally close A1**, stated plainly
rather than glossed over: `fertility`-as-a-FieldGrid-aggregate,
`cultural-influence`, and `beauty` remain unbuilt (the first would
duplicate an axis `location_character` already reads from `FarmGrid`
directly; the latter two have no real data source anywhere in this
codebase without inventing a new subjective-scoring mechanic from
scratch — a genuinely separate design task); migrating `mining_scars`/
`disaster_scars`/the climate grid onto `FieldGrid` also remains
unbuilt (a real refactor of three already-tuned stores, correctly
judged too large/risky to bundle into this batch).

Verified: unit tests for all three fields, a 6000-trial production-
path test confirming the nutrients reproduce bonus through the real
`WildlifeGrid.tick`, a 200-trial production-path test confirming the
scent avoidance through the real `_choose_fission_site` (0/200 sites
landed in a forced-dangerous region), a 4000-tick LLM-disabled soak
with clean round-trip, `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical, and a live dev server + Playwright pass.

## Current state (v1.34.70)

Explicit user instruction: "Tier 1 A1 and Tick off completed items."
Shipped Tier 1's sixth `FieldGrid` field, `noise` — a genuinely
composite field with no new tracked state (`world/fields.py`'s
`FieldGrid.step_noise` is the mean of `population_density`/`traffic`,
both already computed each tick, spread via `ca_operators.diffuse`).
Real consumer: `world/wildlife.py`'s `WildlifeGrid._maybe_recolonize`
(the sole path back from local wildlife extinction) now weights its
recolonization-site draw away from noisy regions
(`RECOLONIZE_NOISE_DAMPENING=0.6`, `noise=None` reproduces the exact
old uniform-choice behavior) — "wildlife resettles the quiet corners
of the map first." UI: 10th "🗺️ fields" overlay mode ("disturbance").

Verified: 2 direct unit tests for `step_noise`, a 3000-trial
production-path test through the real `_maybe_recolonize` confirming
a quiet region draws markedly more arrivals than a noisy one, a
4000-tick LLM-disabled soak with clean round-trip, `scripts/verify_
native_soak.py` (2 seeds x 800 ticks) byte-identical, and a live dev
server + Playwright pass confirming the overlay cycles correctly with
a matching legend.

Also, per the second half of the instruction: re-verified every
open-task checkbox in `docs/ROADMAP-2026-07-REMAINING.md`'s "Open-task
checklist" against current code and ticked/updated everything this
session actually closed since the checklist was last touched (A1's
`ownership`/`noise` fields, A2's `cellular_step` consumer, M1/M9's
environmental-stress reading) — see that file's own per-item notes for
detail; no further stale items found beyond what this session shipped.

## Current state (v1.34.69)

Explicit user instruction: "Continue with roadmap." Shipped Tier 1.5's
residual M1/M9 ask: a labeled "environmental stress"/degradation
reading. `world/spatial_memory.py`'s `compute_environmental_stress`
averages whichever of `mining`/`disaster`/`pollution`/`fertility`
(the subset of `location_character`'s twelve axes that represents real
harm, not just history) a tile actually has, banded via `environmental_
stress_label` into three plain-language readings — pure read-side
unification, no new tracked data. UI: the bare-tile inspector gained
Mining scar/Disaster scar sections (closing a real pre-existing gap —
unlike ruin/road/migration/dry-lakebed, these two scars had never been
shown per-tile, only as a map color + aggregate stat tile) plus the
composite Environmental stress reading itself. `app.js`'s new `field
RegionValue` mirrors `FieldGrid.get_at`'s bucketing math client-side to
read the region-level pollution field for one specific tile. Field
boundaries (M1/M9's other, larger ask) remain open.

Verified: 5 direct unit tests for the composite formula, a live dev
server + Playwright pass (forced-stress tile shows all three new
sections; a pristine tile shows none — the pristine check also
incidentally confirmed the region-bucketing mirror is byte-exact, not
just close), a 4000-tick LLM-disabled soak with clean round-trip,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## Current state (v1.34.68)

Explicit user instruction: "Continue with roadmap." Shipped A2's
`ca_operators.cellular_step` first real consumer. `world/disasters.py`'s
`compute_forest_contiguity` scores each forest tile by local forest
density (1x isolated, up to 2x fully-surrounded at `WILDFIRE_
CONTIGUITY_WEIGHT=1.0`); `tick_wildfire`'s weekly ignition roll now
draws its ignition site weighted by this score instead of flat uniform
choice — a dense forest cluster genuinely catches more often than an
isolated tree, matching how real fires need continuous fuel. Scoped to
WHICH tile ignites only — ignition chance/frequency and the already
native-backed spread-roll mechanic are untouched (the roadmap's own
note against forcing this onto `tick_wildfire`'s sparse-tile-set
roll-batch mechanic still holds; this is a genuinely smaller, safe
surface). `reaction_diffuse` remains the one `ca_operators` primitive
with no real consumer.

Verified: a direct unit test of `compute_forest_contiguity`, a
2000-trial production-path test through the real `tick_wildfire`
confirming weighted ignition-site selection, a 4000-tick LLM-disabled
soak with clean round-trip, `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical.

## Current state (v1.34.67)

Explicit user instruction: "Continue with roadmap." Shipped Tier 1's
fifth `FieldGrid` field + `ca_operators.diffuse` consumer, `ownership`.
`FieldGrid.step_ownership` sources from `World.ownership_history` (A19,
already-real permanent per-tile inheritance-handoff count), summed per
region, normalized, spread via `diffuse` — same shape `traffic`/
`pollution` established. Real consumer: `Population._maybe_welcome_
migrant` gained `region_ownership`/`MIGRANT_OWNERSHIP_PULL=0.3` — the
first genuinely POSITIVE region-field pull in that function (density/
scarcity both only dampen); a deeply-settled region draws up to 30%
more migrants, "word travels that a place has real roots," the plausible
inverse of scarcity's own framing. UI: 7th "🗺️ fields" mode
("settledness"), own color ramp + legend. Also corrected a stale A12
roadmap note (per-instance `Building.material` had already shipped as
an A13 side effect, v1.34.58 — the checklist text still said unbuilt).
Verified via unit tests, a deterministic threshold-crossing test using a
`random.Random` subclass with a fixed first draw (isolates the exact
chance-formula boundary without RNG sampling noise), production-path
tests through real `World.tick()`/round-trip, and a live dev server +
Playwright pass (screenshot confirmed the overlay/legend render
correctly; one pre-existing unrelated `favicon.ico` 404 independently
confirmed via `curl`, not caused by this change). Full detail:
CHANGELOG.md's [1.34.67] entry.

## Current state (v1.34.66)

Explicit user instruction: "Continue with open items in roadmap." Shipped
Tier 3 item 24, B8 `reinforce`/`reinterpret` — CLOSED. `Pillar.
remember()` gained a parallel `memory_access: list[int]` (legacy-
backfilled to zeros): a near-restatement of a recent note (`word_
overlap >= 0.55`) reinforces it (bumps access, no duplicate); a
related-but-differently-phrased note (`>= 0.35`) reinterprets it
(replaces the text in place, also bumps access); otherwise appends as
before. `consolidate()` now folds the LEAST-reinforced notes first
instead of blindly the oldest — a note the pillar keeps returning to
survives longer. One shared method reaches all five pillars at once.
The 0.35 reinterpret threshold was picked empirically (`word_overlap`
isn't stopword-filtered, so unrelated short sentences can hit 0.2-0.3
on shared "a"/"the"/"was" alone — measured against a deliberately-
unrelated batch, max ~0.29, before settling on 0.35). Verified via 7
direct unit tests + 2 production-path tests through the real engine-
attached `village_pillar`. Full detail: CHANGELOG.md's [1.34.66] entry.

## Current state (v1.34.65)

Explicit user instruction: "Start completing items from roadmap." Shipped
docs/ROADMAP-2026-07-REMAINING.md's Tier 3 item 23, B4 reverse-direction
disagreement classification — CLOSED. Extended the Nature->Village
arrow's existing `pillar.disagrees_with(subject)` check to Village->
Innovation's `theory` arrow and all three `ontology.register_concept`-
sourced Innovation->Village `discovery` arrows (propose/merge/evolve).
`composite_entity`'s Innovation->Village arrow deliberately excluded —
a named landmark isn't a competing theory the check applies to.
Verified via two production-path tests through the real `_maybe_
schedule_ontology_proposal` job (real gating/RNG/season-boundary path,
a stubbed synchronous `LLMAdapter`): with vs. without a pre-seeded
conflicting Village theory, confirming `disagreement` vs. the original
flat `discovery`. Full detail: CHANGELOG.md's [1.34.65] entry.

## Current state (v1.34.64)

Explicit user request: "audit the whole codebase and the docs as well.
Find and fix errors that have not been noticed, obvious bugs and subtle
bugs. Moreover, clean up the written documents, there are so many and
so confusing... Finally, update the roadmap file with a checklist of
remaining open tasks." Full detail: CHANGELOG.md's [1.34.64] entry;
root-cause writeups in docs/DECISIONS.md.

**Two real bugs, both long-lived.** (1) Floods were structurally
impossible: `FLOOD_HEAVY_RAIN_PRECIPITATION=0.65` is cleared on 0.01%
of ticks, so `flood_pressure` never left zero and the entire flood
subsystem (submersion, damage, A11 recurrence erosion, M2/M8's
terrain reshaping) was dead code. v0.88.0 fixed a genuine ratchet bug
but changed two variables at once — only the `GAIN/DECAY` rebalance
was needed; the threshold raise overshot past what `compute_weather`'s
EMA smoothing can reach. Re-derived to **0.50**; 0.55 is also dead,
0.45 and below re-ratchet. Confirmed on the real `tick_flood` over a
full sim year: peak pressure 1.63, 4 genuine flood events, 78 ticks
with a tile submerged. (2) The `verify_native_soak.py` seed-3 MISMATCH
annotated since v1.34.0 as "a set-ordering quirk" was **not** set
ordering: it was a 1-ULP float difference in `hydrology_field.
moisture`, traced to `cpp/src/weather.cpp` fusing its EMA blend into
an FMA under GCC's default `-ffp-contract=fast`. Fixed with
**`-ffp-contract=off`** in `setup.py` — load-bearing for every native
module doing `a*b + c*d`. Seed 3 now MATCHes for the first time since
v1.34.0.

**Standing lesson added (the sharper form of the "unreachable
threshold" rule).** Threshold work against `compute_weather` must
sample **all twelve months**. This pass's own first probes used 9,000
ticks = ~90 days = spring only, the driest quarter, and reached two
wrong conclusions from it — including a proposed `weather.py` sky-band
retune that would have made the world rain 43% of the time instead of
23%. Re-measured over 3 seeds x 3 full years, the existing sky bands
match v0.87.12's stated intent almost exactly; **the retune was
reverted, the originals were correct.** Drive `compute_weather`
directly with a real `SimClock` rather than ticking a world, and note
`SimClock.month_name` is capitalized while `_MONTH_BASELINES` is
lowercase-keyed (that mismatch silently emptied a diagnostic table).

Also: dead code removed across four modules (verified unreferenced,
pyflakes clean); four custom AST checkers written for this pass
(closure late-binding, `to_dict`/`from_dict` key asymmetry, mutation
during iteration, out-of-range probability constants) came back clean
or false-positive-only.

**Docs: `docs/` went 20 top-level files -> 11 + `archive/`.** Nothing
deleted — nine finished documents `git mv`'d to `docs/archive/`. New
**`docs/README.md` is the index to read first**: which document
answers which question, which are still authoritative, which are
finished history. Live-document path references updated; references
inside `CHANGELOG.md` and the archives deliberately left as-is (they
are historical statements about where a file was).

**Roadmap: `docs/ROADMAP-2026-07-REMAINING.md` gained an "Open-task
checklist" near the top** — only open items, grouped by its existing
tiers, plus two new sections: "Known scope trims" (real deliberate
decisions, recorded so they are not rediscovered as gaps) and
"Standing verification debt."

## Current state (v1.3.35)

Explicit user directive: several settlement/civic decisions were being
asked of the LLM when they should be computed, LLM explaining
afterward. Five systems converted: geography naming (fully procedural,
zero LLM call, reuses the existing collision-safe fallback pool), era
branch (`era_branch.compute_branch` scores branches by real standing-
building mix, ties favor sticky/then random), town-brain priority
(`town_brain.compute_priority`, renamed from `fallback_priority`, is
now THE decision — applied before any LLM call, job no longer
`critical`), institution objectives (new `institutions.compute_
objective`, per-kind deterministic reads: FAMILY feud/size, COUNCIL
materials/disposition, GUILD currency), narrative direction (`narrative_
direction.compute_themes` reads `Settlement.mood`'s real axes past a
threshold). Each LLM call that remains is narration-only — one
sentence explaining the already-decided value, never choosing a
different one. Also fixed: `/diagnostics`' `llm_model` now reads the
actual `MODEL_PATH` env var when set (was silently drifting from the
real deployed model on an env-only switch); added `trigger_rules_*`/
`wildfire_ignition_ticks_recorded` to the diagnostics snapshot the dev
console already dumps raw (closes the last un-exposed Living Terrarium
fields from v1.3.31-34).

## Current state (v1.8.0)

Explicit user instruction: "Start [Stage] 3's first step" — C3
"Player <-> Pillar chat" (roadmap Stage III step 10, docs/
MASTERCHECKLIST-2026-07-22.md). Full detail: CHANGELOG.md's [1.8.0]
entry.

Generalizes Ask-the-Chronicler to `/ask/{pillar}` for any of the five
cognitive pillars: new `llm/pillar_chat.py` (one shared prompt
template, voiced per-pillar via `self_model["voice"]`), `Pillar`
gained `conversation_log`/`last_question`/`last_answer`/`pending`,
`GET /pillar/{pillar}`/`POST /ask/{pillar}` +
`_schedule_pillar_answer` (same enqueue-now/apply-next-tick seam as
the chronicler). Answers only from the pillar's own real self/world-
model, never raw stats. A resolved exchange reaches that pillar's own
next real cognition call as a `working_memory` note (the same
`emergence_observations` channel B2 already established) — "nudges
enter cognition as weighable inputs, never commands," genuinely wired
rather than asserted. Main-UI panel under the explore menu ("🗣 ask a
pillar"). "Pillars may initiate contact" (stretch goal) not attempted.

Stage III steps 11-14 (B4 inter-pillar bus, B5 Innovation-as-scientist,
B6 Reflection-as-meta-scientist, B7 Humans collective+coordinator) and
all of Stage IV were considered for an autonomous Routine this pass;
explicit user decision via `AskUserQuestion`: "Skip the routine, I'll
ask you to continue manually" — no Routine was created. Every
subsequent roadmap step (this file's v1.9.0 entry onward) is started
only in direct response to an explicit user "next step"/"continue"
message, never queued or auto-chained.

## Current state (v1.34.63)

Explicit user instruction: "Start 18" (Tier 3 item 18, A7 "Grammar-
based procedural systems"). Ships the one unambiguous piece of the
item's three-part bundle: `world/dialect_grammar.py`'s `drift_term`
gained a `steps` param, chaining rule applications where each round is
re-seeded off the PREVIOUS ROUND'S OUTPUT — a genuine recursive rewrite
system, not a flat single mutation. New `Settlement.lineage_depth`
(0 at founding, `+1` per fission) drives the round count at the one
real consumer (`_maybe_schedule_fission`'s inherited-lexicon drift) —
a granddaughter settlement's words now drift measurably further than a
daughter's. `steps=1` (default) is byte-identical to the old behavior.
UI: conditional "Lineage" stat tile.

Layout/architecture staying single-application is left open (a
genuinely bigger lift each). Ritual/recipe-structure grammar: on
inspection, actually contradicts a real prior design decision
(`docs/MASTERCHECKLIST-2026-07-22.md`'s own A7 entry framed it as
"closer to meaning... stays LLM-authored") — correctly left
unattempted, not overlooked. Rules-as-LLM-proposable unattempted.

## Current state (v1.34.62)

Explicit user instruction: "Start tier 3 and queue tier 4 and 5"
(docs/ROADMAP-2026-07-REMAINING.md). Tier 4 (standing re-audit
discipline)/Tier 5 (HearthBench & the Adaptive Runtime) formally
queued, nothing built from either this pass.

Tier 3 item 17 (A5/A6): shipped the validate-step half explicitly
flagged unattempted at v1.16.0/v1.18.0. `llm/ontology.py`'s `validate_
hook` gained an optional `present_tags` param — an `invention_
specialization_category` claim of `agricultural`/`structural` with
zero real affordance overlap against the settlement's own standing
buildings is now rejected instead of trusted outright; `mercantile`/
`general` have no meaningful physical mapping and stay unchecked.
Wired at the one real call site (`_maybe_schedule_ontology_proposal`,
reusing the SAME `present_tags` already computed for the generate-step
grounding). Per-instance `Entity.affordances`/`Entity.properties` (the
item's other, larger named piece) remains open, not attempted.

## Current state (v1.34.61)

Explicit user instruction: "Start B5 and C4" (docs/ROADMAP-2026-07-
REMAINING.md, Part B/Part C, Tier 2 items 15/16).

B5 "Innovation as conscious scientist": CLOSED. Found the item's own
"affordance/reaction query" gap already shipped (v1.16.0/v1.18.0, a
stale roadmap note). The real remaining gap — only `propose` closed
the hypothesize -> observe -> revise loop, not `evolve`/`merge` — is
fixed: both now carry an optional `hypothesis` field (empty = natural
drift, a legitimate answer) and mirror-then-register in the same order
`propose` does, so an evolved/merged concept's own later real adoption
fate can revise Innovation's belief about it in place, just like a
proposed one already can.

C4 "The acceptance gate as law": CLOSED (second real instance). The
runtime-retirement auditor (`ontology.retire_stale_rules`, item 5.1)
only ever covered `TriggerRule` — new `reactions.retire_stale_
composite_reactions` gives `CompositeReaction` (its structural
sibling) the same treatment, run on `composite_reaction_propose`'s own
gated cadence. A fully general state-auditor remains unattempted;
this is a second concrete instance of the pattern, not a
generalization of it.

## Current state (v1.34.60)

Explicit user decision via `AskUserQuestion` (following v1.34.59's
audit): "Design a new memetics consumer" — `world/memetics.py`'s
`weighted_spread_target` gets a second real production consumer, a
genuinely new content type designed from scratch (no existing site had
the right candidate-list shape).

New `Agent.kept_traditions` (plain, FIFO-capped list, `KEPT_
TRADITIONS_CAP=5`): the missing personal-adoption layer over
`Settlement.traditions` — a tradition existing settlement-wide isn't
the same as anyone actually living by it. New `SimulationEngine.
_maybe_spread_tradition_keeping` (zero-LLM-cost, small per-tick roll,
wired into `_TICK_JOBS` right after `_maybe_spread_concepts`) picks a
settlement's tradition and spreads personal keeping of it via `memetics.
weighted_spread_target`, same "candidates weighted by social closeness
to existing carriers" shape ontology concept adoption already proved.
Real consequence: `world/culture_aggregate.py`'s civilization reading
gained a `tradition_keeping_rate` field (agents personally keeping a
tradition, not just its paper existence), nudging `cultural_cohesion`
up by a small bounded amount — reaches the Town Consciousness prompt
and a "Civilization" stat-tile suffix; NPC inspector gained a
conditional "keeps: ..." line. The other two A17 pieces (rumor
fitness-vs-truth, a shared decay/compete step) were out of scope of
this decision and remain flagged exactly as in v1.34.59.

## Current state (v1.34.59)

Explicit user instruction: "Continue A17" — docs-only, no code
shipped. Investigation found each of the item's three remaining named
pieces carries a real, flagged blocker: (1) no second real site
matching `memetics.weighted_spread_target`'s "pick a next carrier from
a candidate list, weighted by closeness to existing carriers" shape
exists in the codebase today (every `rng.choice`/`rng.sample` site was
re-checked); (2) a fitness-vs-truth axis for rumors needs a ground-
truth value per rumor that would contradict Phase G's standing "belief
never has to reconcile with objective reality" principle; (3) the one
safe-looking site for a shared decay/compete step (`Settlement.
lexicon`) has no genuinely live consumer (only `dialogue.py`'s dead-
code general `build_prompt` reads it), and the one genuinely live site
(`recent_topics`/`top_topics()`) risks destabilizing the topic-
diversity tuning v0.87.35 fixed without a live-diagnostic read first.
Filed as an explicit audit finding in the roadmap rather than forcing
code through any of the three; resumes only on an explicit user
decision naming a path.

## Current state (v1.34.58)

Explicit user instruction: "update roadmap if A20 is closed otherwise
complete it. Start A13" — A20 was already closed (v1.34.57); fixed a
stale roadmap summary-index line the prior batch missed. A13
("Chemistry / reaction system") previously shipped the query half
only; this ships the real automatic reactor the spec always named.

`ReactionRule` gains a `rate` field; new `Building.material`/
`reaction_progress` (per-instance, `material=None` = "use the kind's
default"); new `world.chemistry.tick_building_reactions`, called once
per settlement per tick — a standing building whose EFFECTIVE material
matches a rule's reactant, held under that rule's condition for `rate`
consecutive ticks uninterrupted, genuinely converts (clay SHRINE ->
ceramic under sustained heat; fiber HATCHERY -> cured_fiber under
sustained water_and_time). Only clay/fiber can ever fire this way — no
`BuildingKind` defaults to `ore`, an honest, flagged gap. Two
consequences chosen for zero native-parity risk: a one-time
`condition` boost, and `world.materials.building_instance_affordances`
— every future query for that instance reflects the real new material,
wired into Innovation's discovery prompt and the building-descriptor
UI line. UI: click-inspector "Built of" line now reads the real
per-instance material; new 🏺 event icon.

Verified: direct unit tests (full conversion cycle for both real
reactant paths, interruption resets not pauses, no re-firing post-
conversion); a production-path `World.tick()` test to a genuine
conversion; round-trip + legacy backfill; a smoke test confirming the
ontology-proposal query doesn't crash with a converted building
present; a 5000-tick organic soak (the one surviving round-trip diff,
`river_tiles` set-ordering, reproduced identically on unmodified code
— the same pre-existing quirk already documented, not introduced
here); `scripts/verify_native_soak.py` byte-identical; a live dev
server + Playwright pass.

## Current state (v1.34.57)

Explicit user instruction: "Unify folklore/legend pipeline and
continue A20." Two independent slices, one batch.

Folklore/legend unification (A21's last flagged-open gap): new
`Settlement.folklore_persistence_count`/`folklore_persistence_
promoted` — a folk tale that endures unsuperseded across `FOLKLORE_
LEGEND_PERSISTENCE_THRESHOLD=6` consecutive monthly folklore firings
deterministically graduates into `Settlement.legends` (`_promote_
folklore_to_legend`, zero LLM cost — the wording is already settled).
The real fold between the two previously-parallel pipelines: a tale
that keeps being retold long enough without new material IS a legend.

A20 "Multi-scale simulation" — CLOSED. Audit found the doc's own
status line stale: `FieldGrid` gained five more region-aggregated
fields since v1.27.0, already satisfying the "brand-new second field"
gap several times over. The genuinely open half — "'culture'
aggregates settlements' information-ecosystems" — ships now: new
`world/culture_aggregate.py` (pure aggregation, zero new simulation)
reads every named settlement's already-real culture state into one
world-scale reading (dominant tradition-influence category, cultural
cohesion, religions formed, legend/tradition counts). Consumer:
`llm/consciousness.py`'s Town Consciousness prompt (the one genuinely
world-scoped Mind) gains this as optional grounding. UI: a new
"Civilization" main-UI stat tile.

Verified: direct unit tests for both mechanisms; production-path tests
through the real `_maybe_schedule_folklore`/`_note_folklore_
persistence`/`_promote_folklore_to_legend`/`_maybe_schedule_
consciousness` call paths; a 5000-tick LLM-disabled soak with clean
round-trip; `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical; a live dev server + Playwright pass confirming the new
stat tile renders correctly.

## Current state (v1.34.56)

Explicit user instruction: "Continue A21" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 2, "Temporal compression") — closes A21 for real:
v1.34.54's second slice grounded chronicle/folklore in "already
legendary" context and fed legends into Innovation's ontology-proposal
pressure gate, but nothing that actually AUTHORS a tradition or a
religion ever read a settlement's own legends, leaving the checklist's
literal "feed back into tradition/religion... formation" wording only
partially closed.

`llm/culture.py`'s tradition-authoring `build_prompt` and `llm/
religion.py`'s crystallization `build_prompt` both gained an optional
`legends` param (same additive, omitted-reproduces-prior-prompt shape
chronicle/folklore already established) — a new tradition or a
coalescing religion can now genuinely ground itself in a legend the
village already holds as true. Wired at both real call sites. COUNCIL/
GUILD/FACTION institution formation has no equivalent LLM-authoring
hook (deterministic triggers, not narrative context) — that piece
stays covered by the prior slice's pressure-gate feedback. Folklore/
legend pipeline unification remains the one genuinely open piece, per
the source checklist's own "aspirational" framing.

Verified: direct unit tests for both `build_prompt` functions; a
production-path smoke test scheduling both real jobs against a
settlement with a real legend, LLM disabled; a 4000-tick soak with a
clean round-trip (no new persisted state); `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical.

## Current state (v1.34.55)

Explicit user instruction: "Continue with A19" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 2, "Persistent spatial memory") — closes A19's
third and final slice, following the second slice's own flagged gap
("ownership/construction remain unfolded... needs a genuinely new
per-tile HISTORY store").

New `World.construction_history`/`ownership_history`: permanent,
non-decaying per-tile integer counts (deliberately unlike the scar
dicts, which decay — how many times a site has been rebuilt or passed
down is real accumulated history, not a cosmetic mark that should
fade). Written at two already-existing real events, not new ones
invented to source the axis: `construction_history` increments in
`Population._maybe_start_construction` right after its real call to
`Settlement.start_construction`; `ownership_history` increments in
`Population._apply_inheritance` (H7) at the exact point a HUT's
`owner_agent_id` hands off to a living heir. `world/spatial_memory.py`
gains matching `CONSTRUCTION_NOTABLE_COUNT=2`/`OWNERSHIP_NOTABLE_
COUNT=1` thresholds (a rebuild is notable, a first build isn't; a
single inheritance hand-off already is, since H7 requires a death with
a living family heir), normalized 0..1 same as every other axis. Closes
every axis A19's spec names except battles (no combat mechanic exists
to source it — stays genuinely open).

Verified: direct unit tests for both new axes' threshold surfacing;
two production-path tests calling the real `_maybe_start_construction`/
`_apply_inheritance` classmethods with a forced scenario, confirming
the dicts populate through the actual mechanism; a 4000-tick LLM-
disabled soak with a clean round-trip incl. legacy backfill;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## Current state (v1.34.54)

Explicit user instruction: "continue a21" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 2, "Temporal compression") — redirected from the
Tier 3/Tier 0/Tier 5 sequence queued the prior turn; that sequence
stays queued next.

A21's first slice shipped legend detection/narration; this ships its
two remaining named gaps. Feedback: a formed legend now bumps
`Settlement.pattern_signal_counts[f"legend_{subsystem}"]` to
`PATTERN_SIGNAL_BELIEF_THRESHOLD` — the same pressure gate `_maybe_
schedule_ontology_proposal` already reads, so a crystallized legend
measurably biases what the village invents/proposes next, no new
mechanism. Grounding: `llm/chronicle.py`/`llm/folklore.py` both gained
a `legends` param (folklore's distinguishes "already a full legend"
from ordinary folk-tale material, closing a real dedup gap). `llm/
dialogue.py` deliberately NOT touched — audited and found its general
`build_prompt` machinery has been dead code since v1.4.0's voice-pair
redesign; real dialogue only reaches the separate, deliberately
minimal `build_voice_prompt` (an explicit prior user directive this
pass respects rather than works against).

Verified: unit tests (grounding present/absent in both prompts), a
real engine production-path test confirming the exact `pattern_
signal_counts` write makes a settlement read as pressured, a 4000-tick
soak with clean round-trip, native soak byte-identical.

## Current state (v1.34.53)

Explicit user instruction: "start A19" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 2), followed by "queue tier3 and tier 0 and then
tier 5" for subsequent turns — this pass ships A19's second slice
only; Tier 3/Tier 0/Tier 5 are queued next, one complete batch per
turn as established.

A19's first slice (v1.34.49) explicitly flagged traffic/pollution/
fertility as "a different shape" (continuous `FieldGrid` regions / a
farmed-tiles-only dict) and left them unfolded. `world/spatial_
memory.py`'s `location_character_from_dicts` now folds all three in
for real via new `soil_fertility`/`traffic_at`/`pollution_at`
keyword params, each surfacing only past a real notability threshold
(`FERTILITY_NOTABLE_THRESHOLD`/`TRAFFIC_NOTABLE_THRESHOLD`/
`POLLUTION_NOTABLE_THRESHOLD`, all 0.5) — same "absence means
neutral" discipline every other axis holds. `location_character`
resolves `traffic`/`pollution` for the specific tile via `FieldGrid.
get_at`. Nine of the spec's named axes are now real; ownership/
construction remain unfolded (no per-tile HISTORY store exists for
either — real, unscoped follow-up, not another read-side unification).

Verified: direct unit tests (forced-value surfacing, below-threshold
absence, never-farmed-tile absence, category/label completeness), a
production-path test against a real `World` with forced field/farm
state, a 4000-tick engine soak with clean round-trip (no new
persisted state — read-side only), `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical.

## Current state (v1.34.52)

Explicit user follow-up on v1.34.51: "Make elevation render on the
map somehow and hence the erosion. Irrespective of biome boundary."
`Tile.elevation` was never rendered on the map at all — every
elevation-writing mechanism (A11's weekly hydrology erosion, v1.34.51's
quarry formation and flood-recurrence erosion) was only visible when a
change happened to cross a `classify_with_bias` biome band.

`interface/api.py`'s `set_terrain()` payload gained a full dense
`elevation` grid straight off `terrain` (same source `biomes` already
reads — no new backend state). `app.js`'s `drawStaticTerrain` blends
this into a subtle, always-on relief tint (`elevationShadeStyle`,
centered near 0.6, capped so it never overwrites a tile's own biome
color) — a permanent map layer, not a togglable mode, matching the
standing "map is the primary interface" discipline. Cumulative erosion
below a single band-crossing threshold is now genuinely visible as a
gradually shifting shade instead of invisible until it crosses a band.

Verified: `/terrain` payload directly inspected (dense elevation grid
present, matching `World.terrain`); a live dev server + Playwright
pass with a screenshot confirming visible relief shading (dark
deep-water basin, lighter highlands) and no new console errors;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
— pure payload/rendering change, no native module or persisted state
touched.

## Current state (v1.34.51)

Explicit user instruction: "Complete M2/M8" — the one Tier 1.5 item
v1.34.50 left flagged, not attempted, because its two remaining named
examples ("flooding reshapes the land," "quarry scars as actual
terrain change") would reverse a real, twice-documented prior design
decision (mining/disaster scars deliberately cosmetic-only, never a
biome change). This instruction is the explicit product call that
decision was waiting on — ships both.

New `Biome.QUARRY` (appended last, native-storage-safe): `terrain_
evolution.maybe_form_quarries` converts a HILLS tile mined
CONTINUOUSLY, with no interruption, long enough to both reach and hold
`MINING_SCAR_QUARRY_THRESHOLD` (0.95) for `MINING_SCAR_QUARRY_TICKS`
(400) — a real, permanent conversion with an elevation drop, scoped
tight to sustained extreme extraction so ordinary mining stays exactly
as cosmetic as before. Sticky against both climate drift and erosion's
own elevation-driven reclassification, so it never silently reverts.

`disasters.tick_flood` gained an optional `recurrence` counter: a tile
that has flooded the SAME way `FLOOD_RECURRENCE_EROSION_THRESHOLD` (3)
separate times gets a real, permanent elevation erosion on its next
recede instead of always fully restoring the pre-flood biome — reuses
A11's own `classify_with_bias` reclassification rather than a parallel
mechanism. `recurrence=None` (default) reproduces prior behavior
byte-for-byte.

New `World.mining_scar_sustained_ticks`/`flood_recurrence_counts`
(small, self-pruning progress dicts) + `tiles_flood_eroded_total`/
`quarries_formed_total` counters, `quarry_formed`/`flood_eroded` event
categories wired into `TERRAIN_CHANGING_CATEGORIES` both sides. UI:
"Quarries" stat tile, distinct map color, flood-erosion folded into
the existing "Erosion" tile, new event icons.

Verified: direct unit tests (full `maybe_form_quarries` lifecycle incl.
interruption-resets-not-pauses and developed-tile skip; `tick_flood`'s
recurrence-triggered erosion via a real forced-flood scenario), a
`recurrence=None` backward-compatibility test, a real 4000-tick
`World.tick()` production-path run with clean round-trip + legacy
backfill, `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical, and a live dev server + Playwright pass. Closes Tier
1.5 "The Living Map" entirely.

## Current state (v1.34.50)

Explicit user instruction: "Start tier 1.5 and finish as many tasks as
possible in 1 turn" (docs/ROADMAP-2026-07-REMAINING.md's Tier 1.5,
"The Living Map"). Most of Tier 1.5 (M4, M6/M7, M10, M11/M12) was
already shipped in earlier sessions; this pass audited the rest,
caught two stale docs-accuracy bugs, and shipped M1/M9's one
remaining un-built named example.

Docs-accuracy: Tier 1's own summary index (item 2, the A11 entry)
still said A3's rivers-re-carving "remains open" after A11 shipped —
A3's own detailed entry further down the same doc already recorded it
shipped at v1.34.25; fixed the stale summary line. Tier 1.5's M2/M8
status line still framed `Tile.elevation` immutability as "the single
biggest blocker... ALL gated on this one item," when A11 (v1.34.23) +
A3 (v1.34.25) had already resolved that specific blocker — rewrote to
separate "blocker resolved" from what's still genuinely open (flooding
reshapes the land, quarry scars as terrain change). Both of those
remaining M2/M8 examples are flagged, not attempted: `mining_scars`'s
and `disaster_scars`' own docstrings explicitly document a prior
deliberate design decision ("cosmetic state, not a biome change...
stays HILLS, walkable and re-minable" / "No terrain/biome mutation...
cosmetic-only") — building either would reverse that twice-documented
choice, a product call for the user, not a silent code change.

Shipped: `World.dry_lakebed_scars`, a 7th scar-shaped dict (same
additive-gain/weekly-decay/delete-at-zero pattern as `mining_scars`/
`disaster_scars`/`ritual_activity`/`ruin_scars`/`road_scars`/
`migration_trails`) — `hydrology.tick_lakes`'s existing `lake_receded`
branch (a shrinking lake exposing bare ground) now optionally marks
the vacated shoreline tile via `terrain_evolution.apply_dry_lakebed_
scar`, gated by a new keyword-only `dry_lakebed_scars` param that
defaults to `None` and reproduces prior behavior exactly when omitted.
`location_character`'s axis count is now 7 (`dry_lakebed` added to
`LOCATION_HISTORY_CATEGORIES`/`LOCATION_CHARACTER_LABELS`). Bounded by
`hydrology.LAKE_MIN_TILES` — a lake never fully dries up, so this can
only ever mark individual receded edge tiles, never "a whole dried
lake," same honest scoping as every other scar axis. UI: map overlay
(pale silty grey-blue), bare-tile inspector line, "Dry lakebeds" stat
tile — reuses the existing `lake_receded`-triggered terrain resync,
no new event category needed.

Verified: direct unit tests (`apply_dry_lakebed_scar`/`decay_dry_
lakebed_scars`, the new `location_character` axis), a production-path
test driving `hydrology.tick_lakes` with a real shrinking lake
confirming a genuine scar forms, a backward-compatibility test
confirming `tick_lakes(...)` called without the new kwarg reproduces
byte-identical prior behavior, a 4000-tick LLM-disabled engine soak
with clean round-trip + legacy-backfill, `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical, and a live dev server +
Playwright pass confirming the stat tile renders and the map loads
cleanly.

## Current state (v1.34.49)

Explicit user instruction: "finish A19" (docs/ROADMAP-2026-07-
REMAINING.md, "Persistent spatial memory"). `world/spatial_memory.py`'s
`location_character` unification gained a sixth axis (`migration`,
reading `World.migration_trails` — the closest real existing data to
the spec's "ecology" axis) and, more importantly, its own long-flagged
residual gap closed: the `location_character(world, x, y)` wrapper had
had no caller since v1.34.1 — new `location_character_text()` renders
a tile's strongest 1-2 axes as plain language, consumed by `llm/
composite_entity.py`'s new `location_history` param so a newly-named
place's origin story is grounded in what the SPECIFIC site remembers
("also seen a past disaster and old mining activity"), not just the
settlement's single latest event. Closes A19's own "places as actors"
Feeds item. Traffic/pollution/fertility (different shape, continuous
fields) and ownership/construction (no per-tile store) remain
explicitly unfolded; battles has no data source (no combat mechanic).

Verified: unit tests, a production-path smoke test, a full end-to-end
test with a fake LLM client confirming the grounding reaches both the
prompt and the registered entity, a 4000-tick soak with clean round-
trip, `scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-
identical. No UI change — `migration_trails` was already fully
surfaced at v1.34.27. Closes A19.

## Current state (v1.34.48)

Explicit user instruction: "Start the next one and complete as many
as you can this turn" — third mirror-write -> pillar-authored
conversion, chosen to keep the pattern spreading across pillars/scopes
rather than only town_brain.

`institutions.compute_objective`'s COUNCIL branch had the EXACT SAME
`council_disposition` tiebreak shape v1.34.46 already converted for
`town_brain.compute_priority` — unsurprising, both read the same real
per-institution disposition signal at different scope. Reused the SAME
precomputed `village_pillar_lean` value `SimulationEngine._village_
priority_lean()` already builds, rather than inventing a second
parallel signal — one real question ("does the village's own
accumulated sense of itself lean toward growth or safety") asked at a
second scope. Consulted only in the branch's final catchall (no
sitting council, or its disposition itself tied); the materials-need
arm above it and any live council disposition are never overridden.
FAMILY/GUILD branches untouched — neither has an equivalent soft/
tiebreak point yet.

Verified: unit tests (materials-need/live-disposition never
overridden, lean deciding only in the true no-signal case, FAMILY/
GUILD unaffected), a production-path smoke test through the real
`_maybe_schedule_institution_belief` call path, a 4000-tick
LLM-disabled soak with clean round-trip, `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical. ~52 Tier 0 mirror sites
remain unconverted.

## Current state (v1.34.47)

Explicit user instruction: "Pick the next Tier 0 site to convert" —
second mirror-write -> pillar-authored conversion, chosen to spread
the pattern to a second pillar (Innovation) rather than only Village.

`era_branch.compute_branch`'s tiebreak had the same shape as v1.34.46's
`town_brain.compute_priority` site: a primary deterministic score
(a settlement's real standing-building mix) never overridden, followed
by a genuinely arbitrary random pick when tied. New optional `pillar_
leans` param breaks that tie toward whichever tied branch Innovation's
own accumulated `world_model` already leans toward (via `Pillar.
subject_confidence`), falling back to random only once no signal
exists anywhere. `SimulationEngine._maybe_schedule_era_branch`
precomputes the per-branch lean before calling `compute_branch`. Same
echo-chamber avoidance as v1.34.46: `era_branch`'s own mirror subject
never matches a branch-name keyword.

Verified: unit tests (fallback/sticky/tiebreak/never-overrides-a-real-
score cases), a production-path smoke test, a 4000-tick LLM-disabled
soak with clean round-trip, `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical. ~53 Tier 0 mirror sites remain unconverted.

## Current state (v1.34.46)

Explicit user request: "how to go about closing Tier 0," resolved via
`AskUserQuestion` — first conversion site "town_brain priority
(Village)," scope "design the general pattern first." Ships Tier 0's
first genuine mirror-write -> pillar-AUTHORED-decision conversion (the
categorical gap the standalone checklist's v1.34.44 filing flagged as
NOT closeable by another mechanical mirror step).

New `Pillar.subject_confidence(subject_substring)` (`cognition/
pillar.py`): deterministic, zero-LLM-cost read of this pillar's own
`world_model` returning the best-matching entry's confidence (same
scan shape `disagrees_with` established) — the reusable primitive any
future site can fold into an existing soft/tiebreak decision, never a
mechanism handing a pillar a whole decision. First site: `town_brain.
compute_priority`'s existing final catchall tie (same slot `council_
disposition`'s own bounded nudge already occupies) now also weighs
`SimulationEngine._village_priority_lean()` — every urgent arm earlier
in the function stays untouched, preserving v1.3.35's "just compute,
highest wins" directive exactly, since the lean is itself a
deterministic read, never a fresh LLM opinion.

Verified: unit tests, a production-path smoke test, a 4000-tick
LLM-disabled soak with clean round-trip, `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical. Every other Tier 0
mirror site remains write-only — converting further sites is real,
un-scoped follow-up.

## Current state (v1.34.45)

Explicit user instruction: "Start A18." A18 ("Composable event
reactions") had one hand-authored `CompositeReaction` and no general
authoring system — this ships the second slice: a village can now
LLM-propose its own composite reactions, mirroring `TriggerRule`'s
own authoring pattern (`SimulationEngine._maybe_schedule_composite_
reaction_propose`, `llm/composite_reaction_propose.py`,
`world.reactions.register_composite_reaction`), sandbox-validated
(`simulation/sandbox.py`'s `run_counterfactual`) before going live,
never an LLM self-check. New `CompositeReaction` fields (`hook_type`/
`hook_target`/`magnitude`/`origin_settlement_id`/`status`/
`fire_count`) reuse `world.ontology.MECHANICAL_HOOK_TYPES` verbatim
through the existing `_apply_trigger_rule_hook` consumer — no second
effect system; the original "Desperate Times" keeps its own bespoke
`relationship_rupture` consequence unchanged. `World.composite_
reactions`/`next_composite_reaction_id` persisted, legacy-backfill-
aware. Closes A18.

Verified: direct production-path smoke tests (full schedule -> sandbox
-> register pipeline with a fake LLM client; a forced-unsafe sandbox
verdict confirmed rejected/never registered); unit tests for
`validate_conditions`/`matching_reactions`/the cap-and-prune registry
behavior; a 4000-tick LLM-disabled engine soak with a clean round-trip
(incl. legacy backfill); `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical — pure Python, no native module touched.

## Current state (v1.34.44)

Explicit user instruction: "Make a separate list in the roadmap for
just tier 0... Start and A15 for this turn and complete as much as
possible." Docs-only Tier 0 reorganization plus a real A15 slice.

`docs/ROADMAP-2026-07-REMAINING.md` gained a flat "Tier 0 — standalone
checklist" (149 numbered steps, min/max step-size documented from this
doc's own history) — every box checked as of this filing; what's left
needs a fresh design pass (mirror-write -> pillar-authored decision),
not another item at the same size.

A15: `AnimalHerd.hardiness` — a real heritable population-level gene
(a herd is an aggregate, not an individual, so one continuous number
suffices, unlike `Agent.genome`'s diploid system). Seeded with genesis
diversity; inherited with mutation from the surviving local gene pool
on recolonization (falls back to baseline on genuine total extinction).
Scales reproduction rate 0.7x-1.3x, applied in pure Python before the
native grazer-tick fast path — zero native/index parity risk, the
exact concern that previously deferred this item. Bridges
`SpeciesVariant`'s "hardier" trait to this real gene. UI: Wildlife
stat tile gains a conditional hardy/fragile stock reading.

Verified: unit tests (bounds, gene-pool inheritance statistics,
genesis diversity, round-trip), a deterministic threshold-crossing
test of recolonization inheritance, a production-path smoke test of
the SpeciesVariant bridge, a real 5000-tick engine soak with clean
round-trip, a clean `scripts/verify_native_soak.py` run, and a live
dev-server + Playwright pass. Closes A15 for both human and wildlife
domains.

## Current state (v1.34.43)

Explicit user instruction: "I thought you have closed tier 0. Please
do as many slices of if in this turn as possible" — corrected the
premise (Tier 0's own biggest lever, the ~55-scattered-LLM-job pillar
refactor, is real progress but genuinely not closed) and shipped the
one concretely-scoped remainder that was: the Nature causal-reasoning
design note's other two named anomaly candidates (grazer herd local
extinction, forest succession stall), joining the already-shipped
predator-pack extinction trigger. Per-agent cognition's own volume-
safe mirror (Tier 0's other flagged gap) was already closed at
v1.34.34, corrected as a stale note in the roadmap.

`_maybe_schedule_nature_causal_reasoning` is now a thin dispatcher
over three trigger methods, checked in a fixed order (predator, then
grazer, then succession stall), at most one scheduling per tick.
Grazer extinction mirrors the predator trigger's shape exactly.
Succession stall is a real new mechanism: a fallow tile stalled well
past its own effective fallow requirement despite locally favorable
moisture — a genuinely puzzling case (bad luck on the weekly reclaim
roll), distinct from an obviously-dry tile that's skipped rather than
flagged.

Verified: direct production-path smoke tests (fake LLM client) for
both new triggers plus the fixed-priority dispatcher; a real 5000-tick
LLM-disabled engine soak through the actual production path; a clean
`scripts/verify_native_soak.py` run (a full `to_dict()` equality check
hit a pre-existing, unrelated set-serialization ordering quirk in
`roads.ever_established`/`river_tiles`, confirmed present on
unmodified code too — this batch's own fields round-trip clean).

## Current state (v1.34.42)

Explicit user instruction: "Finish A14" — implements the sixth and
final named organism-biology subsystem, `sleep`, closing A14 entirely.

`Agent.sleep_debt` (0.0 = well-rested) is deliberately distinct from
the existing `energy` field: `energy` already swings tick-to-tick with
activity/rest, but `sleep_debt` tracks a much slower-resolving chronic
deficit — it drifts toward `1.0 - energy` at a rate slower than
`immune_strength`'s own adaptation, so a single tired tick barely
moves it; only sustained low energy across many ticks builds real
debt. Real consumer: `_tick_immune_strength`'s target gains a further
drag from `sleep_debt`, on top of (not replacing) its existing
momentary hunger/energy pull — "chronic sleep deprivation wears down
the immune system in a way a single tired day doesn't" is now
mechanical.

UI: a conditional "under-rested/chronically sleep-deprived" line in
the NPC inspector's Personality section, shown only once real debt has
accumulated.

Verified: direct unit tests (drift direction, slow convergence,
bounds, round-trip), a deterministic threshold-crossing test of the
immune_strength consumer, a real 5000-tick LLM-disabled engine soak
confirming organic formation through production + clean round-trip, a
clean `scripts/verify_native_soak.py` run, and a real dev server +
Playwright pass confirming the inspector line renders correctly.

## Current state (v1.34.41)

Explicit user instruction: "Do that as well" — implements A14's
remaining two named subsystems together, `development` and
`fertility`/reproduction, following v1.34.40's `injury-recovery`.
Closes A14 down to a single remaining subsystem: `sleep`.

Deliberate architectural split: `development` is a genuine STORED,
ticked accumulator (real state with history-dependence, round-tripped
like `stress`/`injury`); `fertility` is a PURE DERIVED `@property` — a
direct function of `age_ticks` alone, recomputed fresh on every
access, never stored, zero round-trip surface (chronological age has
no physiological lag against itself).

`Agent.development` (0.0 at birth) grows every tick toward 1.0 by
`DEVELOPMENT_FULL_TICKS` (a bit past `MATURITY_TICKS`), scaled
0.5x-1.2x by nutrition — real childhood stunting under sustained
famine. Deliberately distinct from the existing binary `_is_mature`
gate: that gate still decides WHETHER an agent can reproduce/work/hold
office at all; `development` is a slower "how fully grown are they"
reading underneath it. A migrant starts at `development=1.0` (already
an adult); a newborn starts at 0.0. Real consumer:
`Population.carrying_capacity`'s labor term now sums each mature/
healthy adult's own `development` reading instead of a flat +1 — a
chronologically-mature young adult who grew up through a hard famine
contributes measurably less labor capacity than a fully-grown peer.

`compute_fertility(age_ticks)` is the real age-based reproductive
curve: 0 before maturity, rises 0->1.0, plateaus at 1.0, then declines
to a floor of 0.15 (never exactly 0, matching every other reproduction
gate's "meaningful, never a hard block" scale). Real consumer:
`_maybe_reproduce`'s roll is now also scaled by the courting pair's
average fertility, stacking with `stress`'s existing psychological-
drag factor — two independent real signals on one mechanic.

UI: a conditional "still growing" line and a conditional plain-
language fertility reading, both in the NPC inspector's Personality
section.

Verified: direct unit tests (fertility curve at every phase boundary,
the property, development's round-trip), deterministic threshold-
crossing tests for both real consumers, a real 5000-tick LLM-disabled
engine soak confirming organic formation through production + clean
round-trip, a clean `scripts/verify_native_soak.py` run, and a real
dev server + Playwright pass confirming both new inspector lines
render correctly.

## Current state (v1.34.40)

Explicit user instruction: "Continue A14." Third of the six named
organism-biology subsystems: `injury-recovery`, following v1.34.37's
`stress`.

Predator attacks previously left surviving agents with zero lasting
trace. `Agent.injury` (0..1) is now bumped on a non-lethal predator
attack and heals every tick via exponential smoothing, scaled 1.5x
faster for a well-fed/rested agent and 0.5x for a starving/exhausted
one — same nutrition/rest coupling `immune_strength` established,
applied to the healing rate. Real consumer: an already-injured agent
is more vulnerable to a FURTHER attack (kill chance scaled up to
1.6x), applied in pure Python after the existing native-or-fallback
kill-chance computation — zero native/fallback parity risk. UI: a
conditional "injury: healing/badly hurt" line in the NPC inspector,
shown only when an agent has actually been hurt.

Verified via direct unit tests (recovery-rate scaling, round-trip),
a deterministic threshold-crossing test of the predator-attack
consumer, a real 5000-tick LLM-disabled engine soak confirming real
`predator_attack` events fired through production and injury formed/
healed organically with a clean round-trip, a clean `scripts/
verify_native_soak.py` run, and a real dev server + Playwright pass.
Reproduction and development (A14's last two named subsystems)
remain open.

## Current state (v1.34.39)

Explicit user instruction: "Finish A4." Docs-only — direct code
inspection found A4's remaining two named sub-domains already
satisfied, contrary to the item's own stale note:
`RoadNetwork.tick()`/`Settlement.tick()` already decay `wear`/
`condition` continuously every tick (infrastructure); gossip
contagion + `memetics.weighted_spread_target` already propagate on
the real social graph every dialogue exchange (information).
`spread_rumor` was checked as a candidate for the memetics weighting
and found to genuinely not benefit (no carriers exist at first
arrival, so it already degrades to the same uniform selection). Also
fixed a stale duplicate "### A4" doc section left over from v1.34.38's
edit. This closes A4 entirely.

## Current state (v1.34.38)

Explicit user instruction: "Continue with A4" ("Continuous systems vs.
scripted events," docs/ROADMAP-2026-07-REMAINING.md). First slice:
economy's own literal ask, "resource/price fields that flow" — a
`scarcity` field (fifth `FieldGrid` field).

`settlement.buildings.compute_resource_fill` factors the granary/
materials fill math out of the existing `tick_market_prices` (behavior
unchanged); `FieldGrid.step_scarcity` sources `1 - avg(food_fill,
materials_fill)` per settlement, averages per region, spreads via
`diffuse`. Real consumer: `_maybe_welcome_migrant`'s chance now dampens
up to 30% in a visibly struggling region, same bounded shape
`MIGRANT_DENSITY_DAMPENING` already established. UI: 7th "🗺️ fields"
map overlay mode, own green-amber-red color ramp.

Verified via direct unit tests, a deterministic threshold-crossing
test of the migrant-welcome consumer, a real 4000-tick LLM-disabled
engine soak confirming organic field formation + clean round-trip, a
real dev server + Playwright pass confirming all seven field modes
cycle correctly, and a clean `scripts/verify_native_soak.py` run.
Infrastructure/information (A4's other two named sub-domains) remain
open.

## Current state (v1.34.37)

Explicit user instruction: "Continue as many remaining tier 1 items as
possible in this turn." First slice this turn: A14's second organism-
biology subsystem, `stress` (following v1.34.36's `traffic`).

`Agent.stress` (0..1) drifts toward a target from real, already-
tracked acute-threat signals — fear/grief emotions, a hunger crisis,
active illness, a hardened feud — same "continuous state modulating an
existing tuned mechanism, never replacing it" shape `immune_strength`
established. Real consumer: `_maybe_reproduce`'s roll is scaled down
by up to 50% for a fully-stressed courting pair — "chronic stress
suppresses fertility," bounded, never a hard block. UI: a plain-
language stress reading in the NPC inspector, next to the existing
immune-constitution line.

Verified via direct unit tests (target convergence per driver, round-
trip, the reproduction-penalty formula), a real 4000-tick LLM-disabled
engine soak confirming organic formation + clean round-trip, a clean
`scripts/verify_native_soak.py` run, and a real dev server + Playwright
pass confirming the inspector renders a live value.

## Current state (v1.34.36)

Explicit user instruction: "Tier 1 as many slices as you can build in
this turn." Second slice this turn (following v1.34.35's `pollution`):
a FOURTH `FieldGrid` field + `ca_operators.diffuse` consumer, `traffic`.

`FieldGrid.step_traffic` sources from `World.roads.wear` (already-real
per-tile road-wear state), normalized per region and spread via
`diffuse`. Real consumer: `_maybe_schedule_caravan`'s monthly visit
chance gained a `traffic`-scaled multiplier (up to 1.5x at full
traffic), stacking with the existing market/relation multipliers —
"trade follows roads" is now mechanical. UI: 6th "🗺️ fields" map
overlay mode, own blue-cyan-white color ramp, same weekly resync
channel as the other three fields.

Verified via direct unit tests, a deterministic threshold-crossing
test of the caravan consumer, a real 4000-tick LLM-disabled engine
soak confirming organic field formation + clean round-trip, a real
dev server + Playwright pass confirming all six field modes cycle
correctly, and a clean `scripts/verify_native_soak.py` run.

## Current state (v1.34.35)

Explicit user instruction: "Implement as many slices of tier 1 as
possible." A9/A11/A3 were already shipped; the two genuinely open Tier
1 items (A1/A2) ship a THIRD `FieldGrid` field + `ca_operators.diffuse`
consumer together, `pollution` — same "field and consumer in one
slice" shape `disease_pressure` established.

`FieldGrid.step_pollution` sources from two already-real producers:
standing FACTORY/POWER_PLANT/OIL_RIG buildings and `World.mining_
scars` intensity (buildings weighted dominant), normalized and spread
via `diffuse`. Real consumer: `FarmGrid.plant()` gained a `pollution`
yield-penalty factor (bounded floor 0.6, same inverse shape
`moisture`'s factor has) — "industry chokes the fields nearby" is now
mechanical. UI: 5th "🗺️ fields" map overlay mode, own color ramp
(grey-green -> olive -> smog purple-grey), same weekly resync channel
as `population_density`/`disease_pressure`.

Verified via direct unit tests, a real 4000-tick LLM-disabled engine
soak confirming organic field formation + clean round-trip, a real
dev server + Playwright pass confirming all five field modes cycle
correctly, and a clean `scripts/verify_native_soak.py` run.

## Current state (v1.34.34)

Explicit user instruction: "As many slice of tier 0 as you can in this
turn." Tier 0's mechanical mirror/observe-interpret/attention-budget/
inbox-outbox extension work was already fully closed (v1.34.20) — the
two items genuinely still open under Tier 0 were D11 (per-agent
cognition's volume-safe mirror, scoped-not-built pending a design
pick) and a scoped-but-not-built new Nature causal-reasoning job. Both
ship this pass.

D11: `_apply_pending_cognition_results` mirrors a core-cast agent's
goal CHANGE into `humans_pillar.memory` — option (a) of the design
note's three candidates. Volume gate is free: every entry reaching
this loop is already a genuine LLM-authored result (fallback never
queues into `_pending_goal_results`), and only an actual change (not
a same-goal reaffirmation) mirrors.

Nature causal reasoning: new `llm/nature_causal_reasoning.py` +
`_maybe_schedule_nature_causal_reasoning` — a genuinely NEW cognition
point, not a mirror. Reactive: fires when `wildlife.summary()
["predator_packs"]` crosses from >0 to 0, grounded in the specific
anomaly plus real Nature Body state (predator pressure ratio, prey
scarcity, disaster scars, season). `critical=True`; output always
`status="hypothesis"`, written to `nature_pillar.world_model` and a
new `world.ontology.CausalThread` (`settlement_id=None`).

Verified via direct production-path smoke tests for both (fake-LLM-
client driven for the Nature job, confirming exactly-once scheduling
and correct content) plus a real 4000-tick LLM-disabled engine soak
and a clean `scripts/verify_native_soak.py` run.

## Current state (v1.34.33)

Explicit user instruction: "Implement that and do as many slices as
you can per turn" — the responsive-canvas redesign, the one item left
open in M6/M7 after v1.34.30-.32's legends/gradients/hotspots/
thresholds. **Closes M6/M7 and all of "The Living Map" (Tier 1.5).**

The map's drawing buffer (`canvas.width`/`.height`, world pixels =
tiles * `CELL`) stays the one true coordinate system, untouched — only
the CSS display size now tracks the actual viewport (new `resizeCanvas
Display()`, bounded `[0.3x, 1.5x]` of the buffer), wired at every
`drawStaticTerrain()` call plus a debounced `window.resize` listener.
New `canvasEventPoint()` gives mouse handlers both raw CSS-pixel
offsets (tooltip position) and buffer-scaled offsets (`screenToGrid`/
zoom-around-cursor math) — same pattern the relationship-graph
canvas's hover handler already used elsewhere in this file
(`scale = relCanvas.width / rect.width`); drag-pan's delta gets the
same scale correction so panning stays pinned to the cursor regardless
of display scale. `#map-panel`'s `flex: 0 0 auto` auto-tracks the new
canvas size with no extra panel-sizing code; the minimap/season-
vignette overlays needed no changes (already fraction-/`inset`-based).

Verified via `node --check`, a real dev server + Playwright pass
across three viewport sizes confirming the canvas actually resizes to
fit each one, a dedicated click-accuracy test (exact expected tile hit
at a 1.15x display/buffer scale), and a zoom+pan+click sequence
confirming no coordinate drift from the buffer/display scale
correction.

## Current state (v1.34.32)

Explicit user instruction: "Continue that" — the "thresholds" quarter
of M6/M7's four-part ask (docs/ROADMAP-2026-07-REMAINING.md, Tier
1.5), left open by v1.34.31's gradients+hotspots slice.

Audited all four field overlay modes against their real backend
constants before drawing anything, per the standing "no cosmetic-only
marks" discipline: `farms.SOIL_FERTILITY_MIN` is an asymptotic floor,
not a decision boundary; `MIGRANT_DENSITY_DAMPENING`/`OUTBREAK_
DISEASE_PRESSURE_WEIGHT` are continuous multipliers with no
qualitative cutoff. Moisture alone has a genuine two-sided mechanical
threshold — `hydrology.WETLAND_FORM_MOISTURE_THRESHOLD` (0.75) — a
tile sustained above it can convert to a real different biome (M4's
`tick_wetlands`). New `drawFieldContour` traces a real isoline via
per-cell edge-crossing detection, wired only into moisture mode; the
field legend gains a matching "wetland-forming threshold (0.75)" line,
shown only there. Deliberately did not fabricate a threshold line for
the other three modes.

Verified via `node --check` plus a real dev server + Playwright pass
confirming correct show/hide of the legend threshold line across all
four modes and a clean contour render with no regression to v1.34.31's
gradients/hotspots. A full responsive-canvas redesign remains the one
still-open rest of M6/M7.

## Current state (v1.34.31)

Explicit user instruction: "Continue larger remaining scope" — the
larger, explicitly-flagged rest of M6/M7 left open by v1.34.30's
legend-only slice. Ships two of the doc's three remaining asks
("gradients" and "hotspots") in one pass since they share the field
overlay's own paint loop; "thresholds" (contour banding) and a full
responsive-canvas redesign stay open.

`FIELD_COLOR_STOPS` (interface/static/app.js) replaces each of the
four field modes' flat single-hue alpha with a real 3-stop RGB
gradient (`lerpColorStops`) — moisture tan->green->blue, soil
fertility red->tan->green genuinely centered on 0.5, population
density/disease pressure both pale->orange->red heat ramps.
`paintFieldCell` is the one shared helper all four `renderFieldOverlay`
branches now call. Each render pass also tracks the field's own real
peak (soil fertility tracks whichever value is furthest from the 0.5
neutral point, not the raw max) and draws a genuine hotspot marker
(white ring) there, floored at `FIELD_HOTSPOT_MIN_VALUE` so an empty
field doesn't get a meaningless marker. The legend bar is generated
live from the exact same `FIELD_COLOR_STOPS` array the overlay paints
from (`stopsToCssGradient`), so legend and overlay can never drift
apart; new `#field-legend-peak` line surfaces the live hotspot
coordinate.

Verified via a real dev server + Playwright pass: confirmed both
gradients render correctly, confirmed a real hotspot ring appears on
a genuinely-saturated moisture tile with a matching legend line, and
confirmed soil fertility correctly shows NO hotspot on a fresh
unfarmed map rather than a spurious one. Frontend-only, no backend/
native-soak surface touched.

## Current state (v1.34.30)

Explicit user instruction: "Continue" — M6/M7 "field-overlay legend"
(docs/ROADMAP-2026-07-REMAINING.md, Tier 1.5), the last open item in
"The Living Map" after M1/M9, M4, and M10 closed this session. The
doc's own four-part ask ("gradients, hotspots, thresholds, legends"
against Cities: Skylines/Timberborn/Dwarf Fortress conventions) is a
genuine larger UI redesign — this ships the "legends" quarter only,
the smallest self-contained slice: the "🗺️ fields" overlay (moisture/
soil fertility/population density/disease pressure) had no legend at
all, so a color never said what value it represented.

New `#field-legend`: shown only while a field mode is active,
mirroring each mode's real color mapping (not a generic scale) with
plain-language low/high labels ("depleted -> rich" for fertility).
Real collision caught in verification, not assumed: the first
placement (bottom-left) overlapped `#consequences-strip`'s existing
home there — repositioned to stack above the minimap instead.

Verified via a real dev server + Playwright pass: clicked all four
overlay modes, confirmed correct show/hide and labels, screenshotted
two modes directly (soil moisture, soil fertility's bidirectional
amber-to-green gradient) confirming clean, non-overlapping rendering.
True multi-stop gradients/hotspot markers/a full responsive-canvas
redesign remain the larger, still-open rest of M6/M7 — flagged, not
attempted. This closes every fully-scoped item this pass found in
Tier 1.5 "The Living Map."

## Current state (v1.34.29)

Explicit user instruction: "Continue" — M10 "base map readability"
(docs/ROADMAP-2026-07-REMAINING.md, Tier 1.5), the roadmap's own
flagged item needing "a direct look before scoping a fix." Took that
look: launched a real dev server, ticked a real world forward, and
screenshotted the default UI via Playwright.

Real finding: at the old `CELL=8`, the default 64x64 world's map
canvas was a fixed 512x512px element — a small corner of any real
browser window, contradicting this file's own standing Observatory UI
direction ("the map is the primary interface, read at a glance").
Fixed the one safe lever available without a full responsive-canvas
rewrite: `interface/static/app.js`'s `CELL` raised 8 -> 12 — every
draw call and every mouse-position calculation already derives from
this one constant, so the change is uniform and low-risk.

Verified via screenshot (map now visibly dominates the layout) and a
real Playwright click test (a known screen position resolved to the
correct tile, inspector opened with real content — including a live
migration-trail reading, confirming v1.34.27's mechanism is genuinely
visible) plus a zoom/hover/minimap check. Closes Tier 1.5's M1/M9 + M4
+ M10 batch — only M6/M7 (the larger responsive-canvas/reference-game-
quality overlay redesign) remains open in "The Living Map."

## Current state (v1.34.28)

Explicit user instruction: "Continue" — closes M4 "The Living Map"
(docs/ROADMAP-2026-07-REMAINING.md, Tier 1.5), the wetland/marsh half
flagged open in v1.34.27's own entry.

New `Biome.WETLAND` (appended LAST in the enum — the native `Terrain
Grid` backend encodes biome as an int index into `tuple(Biome)`, so a
new member must only ever append, never insert). `world/hydrology.py`'s
new `tick_wetlands` (monthly): a GRASSLAND tile whose moisture AND
groundwater both stay near-saturated for 6 CONSECUTIVE months converts
to WETLAND; reverts once it dries below a lower hysteresis threshold.
Progress resets to absent (not paused) on any interruption — genuinely
sustained conditions required, same discipline as the scar-shaped
dicts. New `World.wetland_progress` tracks the streak. Real consequence
needed no bespoke consumer: WETLAND is deliberately in neither
`WALKABLE_BIOMES` nor `FARMABLE_BIOMES`, so it's an immediate real
constraint on movement/farm siting through existing biome-gated
systems — the same class of consequence any terrain reclassification
already has. UI: "Wetlands" stat tile (reads the existing `biome_
counts` field), map color, `wetland_formed`/`wetland_dried` wired into
`TERRAIN_CHANGING_CATEGORIES`.

Verified: direct smoke tests (sustained-streak formation, interrupted-
streak reset, reversion, developed-tile protection); a `WALKABLE_
BIOMES`/`FARMABLE_BIOMES` exclusion check; a real `World.create_new`/
`tick()` production test (lowered thresholds to force formation) with
a clean round-trip incl. legacy backfill; an unmodified-defaults 4000-
tick soak confirming no crash; `scripts/verify_native_soak.py` (2
seeds x 800 ticks, twice) byte-identical — the new Biome member's
native int-index mapping is derived automatically (`_BIOME_LIST`),
exercised by every soak run. Closes Tier 1.5's M1/M9 + M4 batch; M6/M7
(UI redesign) and M10 (base-map audit) remain open.

## Current state (v1.34.27)

Explicit user instruction: "Continue" — M4 "wildlife migration
trails" (docs/ROADMAP-2026-07-REMAINING.md, Tier 1.5), the natural
next slice after v1.34.26's M1/M9, per the roadmap's own note that
migration trails are "same shape as `ritual_activity`, different
trigger."

New `terrain_evolution.apply_migration_trail`/`decay_migration_trails`
+ `World.migration_trails` — the 6th scar-shaped dict, gained via
`WildlifeGrid.tick`'s new optional `migration_trails` param (`None`
default reproduces the exact pre-M4 behavior/RNG stream, verified).
Real consequence is a genuine feedback loop rather than a downstream
consumer: a GRAZER herd's move-candidate selection weights toward
tiles with existing trail intensity — herds reuse the same crossings,
so the mark-forming code and its own consumer are one mechanism.
Scoped to GRAZER only ("grazing patterns," not predator paths). UI:
"Migration trails" stat tile, a faint map overlay, bare-tile inspector
line — rides the existing 20s `/terrain` periodic refetch (same
channel as moisture/soil_fertility) rather than a new life-event
category, since trails accumulate across many roaming tiles rather
than a few discrete sites.

Verified: direct smoke tests (gain/cap/decay, real grazer-movement
trail formation over 500 ticks); a `migration_trails=None` parity test
confirming byte-identical behavior against the pre-M4 code path; a
real `World.create_new`/`tick()` production test (4000 ticks) with a
clean round-trip incl. legacy backfill; `scripts/verify_native_soak.py`
(2 seeds x 800 ticks, and again after the broadcast-layer changes)
byte-identical — pure Python. M4's wetland/marsh concept remains open,
flagged for a future slice.

## Current state (v1.34.26)

Explicit user instruction: "Continue tier 1.5" — M1/M9 "old road
beds" (docs/ROADMAP-2026-07-REMAINING.md, Tier 1.5 "The Living Map"),
the roadmap's own flagged gap: a fully-decayed established road left
zero trace, unlike mining/disaster/ritual/ruin scars.

New `RoadNetwork.ever_established` (`world/roads.py`) distinguishes a
genuinely-established road from a briefly-visited tile; `tick()` now
returns positions abandoned this tick. New `terrain_evolution.apply_
road_scar`/`decay_road_scars` + `World.road_scars` — same additive-
decaying-dict shape as `mining_scars`/`disaster_scars`/`ruin_scars`,
gained via `Population._update_roads`, decayed weekly alongside the
other three. Real consumer (A9 discipline): `world/spatial_memory.py`'s
5-axis `location_character` now includes `"road"`; `Population.
_choose_build_site` applies a real (smaller-than-ruin) site bonus —
"the village rebuilds along its old travel corridors." UI: "Old roads"
stat tile, a faint map overlay, bare-tile inspector line, `road_
scarred` wired into both Python and JS `TERRAIN_CHANGING_CATEGORIES`.

Verified: direct smoke tests (establish-vs-pass-through distinction,
decay, round-trip incl. legacy backfill); a real `World.create_new`/
`tick()` production-path test confirming the mechanism fires end-to-
end with a clean round-trip; `scripts/verify_native_soak.py` (2 seeds
x 800 ticks, and again after the broadcast-layer changes) byte-
identical — pure Python, no native module touched. Field boundaries
and a labeled environmental-stress reading (the rest of M1/M9) remain
open, flagged for a future slice.

## Current state (v1.34.25)

Explicit user instruction: "Continue roadmap" — A3 "rivers re-carving
their course" (docs/ROADMAP-2026-07-REMAINING.md, Tier 2 item 5),
unblocked by A11's erosion (v1.34.23) actually making `Tile.elevation`
a live-written value.

New `hydrology.river_sources_used(seed, terrain)` factors out
`generate_rivers`'s deterministic source-selection so it can be
captured once at genesis (`World.river_sources`) and reused for every
future re-carve — sources must stay fixed at their ORIGIN even if
erosion later changes the biome there. New `hydrology.recarve_rivers`:
monthly (`World._tick_terrain`'s `month_end` block, alongside climate
drift), re-walks each source by the same steepest-descent rule against
CURRENT elevation. A tile no longer on the path reverts to its
elevation-derived biome (`classify_with_bias`); a newly-visited tile
becomes `Biome.RIVER`. Developed tiles (building/vehicle/farm) are
protected both directions, reusing `terrain_evolution.py`'s
`_is_developed` directly (no circular import). New `World.river_tiles`/
`river_sources` persisted state (genesis-captured, legacy-backfilled),
`river_tiles_shifted_total` counter, `river_recarved` event category.
UI: "Erosion" stat tile extended to also report riverbed shifts.

Verified: direct smoke tests (deterministic reproduction on unchanged
terrain, genuine course-shift under a real elevation reshape including
a correct water-terminus edge case caught during test design, reverted
tiles correctly reclassified, developed-tile protection, idempotence
on a stable course); a real 4000-tick engine run confirmed a clean
`World.to_dict`/`from_dict` round-trip through the actual production
path; both legacy-backfill branches tested directly; `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical. Closes
A3 — the LLM-vs-procgen settlement/culture question stays flagged
open, not a gap.

## Current state (v1.34.24)

Explicit user instruction: "Start A1 and A2" (docs/ROADMAP-2026-07-
REMAINING.md, Tier 1 items 3-4) — both had exactly one real consumer/
field before (`population_density` for A1, forest succession for A2);
this ships their second slice together, as one mechanism rather than
two, since the natural next field and the natural next diffusion
consumer turned out to be the same thing.

New `FieldGrid.step_disease_pressure` (`world/fields.py`): recomputes
a raw regional sick-fraction census each tick, then spreads it via
`world/ca_operators.py`'s `diffuse` into neighboring regions —
contagion risk is regional, not confined to exactly where sick agents
stand right now. Real consumer: `Population._maybe_outbreak`'s
index-case draw now weights each healthy agent by their own region's
`disease_pressure` (`weight = 1.0 + pressure * OUTBREAK_DISEASE_
PRESSURE_WEIGHT`) instead of a flat uniform choice — a region
bordering a real outbreak becomes measurably more likely to seed the
next spontaneous case, never a certainty (floor weight 1.0). Only
changes WHO an outbreak picks once it's already rolled true — never
whether/how often it fires. UI: fourth mode on the existing "🗺️
fields" map overlay toggle.

Verified: direct smoke tests (diffusion spreads from a forced sick
cluster into neighbor regions, empty world stays zero); a genuine
20,000-trial weighted-distribution test with a real (not mocked)
`random.Random` confirmed a 5x-weighted region was picked ~4.97x more
often, matching the design almost exactly — an earlier attempt using
a rigged always-return-0 RNG produced a degenerate 100/0 split and was
caught and redone properly; a real engine run with agents forced sick
mid-run confirmed the field populates through the actual production
tick path; a 4000-tick round-trip and `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) both clean.

## Current state (v1.34.23)

Explicit user instruction: "Start next roadmap item" — A11 "Continuous
hydrology" (docs/ROADMAP-2026-07-REMAINING.md, Tier 1 item 2, the
roadmap's own "highest-leverage remaining item": blocks A3's rivers-
re-carving and Tier 1.5's mutable-elevation items). First slice
(surface moisture flow, v1.13.0) explicitly flagged groundwater and
erosion as unbuilt — both ship now.

Groundwater: new per-tile `HydrologyField.groundwater` reservoir,
distinct from surface moisture — wet land infiltrates into it weekly,
dry land seeps back out (base-flow/spring effect), small constant
percolation loss keeps it bounded. Erosion: `Tile.elevation` turned
out already storage-layer mutable (native `TerrainGrid` and the Python
fallback both accept/store any elevation value since v0.74.1) — no
storage-layer change needed, `tick_erosion` is simply the first real
writer of a new elevation value. Reuses `tick_hydrology`'s steepest-
descent neighbor search: a genuinely wet tile moves a small, capped,
mass-conserving fraction of its elevation to its lowest neighbor,
skipping water/RIVER neighbors, re-deriving biome via `classify_with_
bias` whenever elevation crosses a real threshold (the one real
coherence hazard, since every other consumer keys off `.biome`, not
raw elevation). Weekly, right after `tick_hydrology` in `World._tick_
disasters`. New `terrain_eroded` event category, `World.tiles_eroded_
total` counter, UI: groundwater added to the "Soil moisture" tile,
new "Erosion" stat tile.

Verified: direct smoke tests (elevation-gradient smoothing with exact
mass conservation over 400 weeks, groundwater/moisture bounds under
200 alternating wet/dry weeks, flat-terrain zero-erosion edge case,
round-trip, legacy-snapshot backfill); a real 3000-tick engine run
(LLM disabled) confirmed both mechanisms fire through the actual
production path with a clean round-trip; `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical — erosion's elevation
writes go through the same `TerrainGrid` API every other terrain
mutator already uses, no new native-parity risk. Closes A11. A3
(rivers re-carving) and Tier 1.5's M2/M8 are now unblocked but not
attempted — natural next step, not auto-chained.

## Current state (v1.34.22)

Explicit user instruction: "For D6 at some number of villagers as
threshold promote them to collective NPCs instead of single NPCs.
These can be districts, smaller towns or something like that. Take
hints from the doc itself" — implements D6 (docs/ROADMAP-2026-07-
REMAINING.md), the last open Tier 0.5 item, closed scoped-not-built in
v1.34.21.

New `hearthmind/settlement/district.py`: once a settlement's
individually-simulated non-core population crosses `DISTRICT_
INDIVIDUAL_CAP=250`, the least-prominent excess is genuinely removed
from `Population.agents`/the native `AgentStore` AND from every
surviving agent's `Ledger` entry for them (same per-survivor cleanup
`_apply_deaths` established, v0.42.0, without grief/memorial/
inheritance) and folded into a `District`'s aggregate population — the
actual fix for D6's diagnosed O(population) social-surface problem, not
a cosmetic count. `DISTRICT_MAX_POPULATION=150` caps a single district
before a new named ward spins up (the "smaller towns" half of the
directive). Core-cast agents and any living MAYOR are never
candidates. A `District` has no beliefs/cognition/LLM authorship —
closer to `FarmGrid`/`WildlifeGrid`: ticked daily via `tick_district`
(fractional-accumulator births/deaths, `avg_hunger` exponentially
smoothed toward the settlement's individually-simulated average),
plus a small per-capita passive materials contribution; sustained
famine can genuinely dissolve a district. Deliberate scope trim,
recorded in `SimulationEngine._tick_districts`'s own docstring:
`carrying_capacity()` is NOT adjusted for collectivized population
this pass — districts are a separate, additive population figure so
existing population-growth tuning isn't disturbed without live-test
ability; folding districts into carrying capacity is flagged future
work. UI: new "Districts" main-UI stat tile.

Verified: direct production-path smoke tests against the real
`Population`/`Settlement` classes (collectivization, Ledger cleanup,
materials contribution, starvation dissolution, core-cast protection,
below-cap no-op, `to_dict`/`from_dict` round-trip); a real engine-level
test (temporarily lowered thresholds, 3000 real ticks through
`SimulationEngine._tick_once`, LLM disabled) confirmed districts form/
narrate/round-trip through the actual production path — caught and
fixed one real bug in the process (`_append_emergence`'s `kind` used
an invalid `"observation"` value, not a member of `emergence.
OBSERVATION_KINDS`; corrected to `"opportunity"`/`"unexplained_
shift"`); `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical — no native module touched.

## Current state (v1.34.21)

Explicit user instruction: "Scope this problem for some other tier
and finish tier0.5 now." Per-agent cognition's volume-safe mirroring
design (the practical ceiling flagged since v1.34.7) is filed as Tier
3 item 30 in docs/ROADMAP-2026-07-REMAINING.md — scoped with three
named volume-gate candidates, not designed further. Every item in
Tier 0.5 (D1-D10, filed v1.34.4) closed with a real decision: D5
shipped (a `RULE_PROPOSE_NUM_PREDICT_MULT` token-headroom fix, same
shape `PERSONAL_BELIEF_NUM_PREDICT_MULT` already uses — NOT the JSON
schema the item originally proposed, which would have silently killed
`rule_propose`'s deliberate reasoning trace); D1/D2/D3/D4/D9
re-confirmed via code-level re-audit (no live LLM server in this
environment to re-run the original live-measurement asks against);
D6/D8 scoped-not-built with concrete design notes (D6 pairs with
Tier 5's B10, D8 pairs with B8's reinforce/reinterpret); D7 closed as
already-working; D10 attempted at a longer horizon (60k, then 30k
ticks) but honestly incomplete — per-tick cost grows with population
and this session's time budget ran out before either finished (killed
~10k ticks in, no failure seen); the standing 4,000-tick soak shows no
regression from D5's change, but a genuine 60k+-tick re-verification
is still open, a rerun needing more wall-clock budget, not a design
question. Full detail: CHANGELOG.md's [1.34.21] entry.

## Current state (v1.34.20)

Explicit user instruction: "Continue and finish attention scaled site
in one go." Fourteen more real B4 inbox/outbox arrows, chosen for
genuine content value, closing the decision for every one of the 34
attention-scaled sites (v1.34.18) rather than leaving them
ambiguously open — either a real arrow or a documented reason not to.
Village->Humans on tradition/folklore/festival/institution_belief/
diplomacy; Village->Reflection on legend_detection/laws; Village-
>Innovation on guild_founding; Humans->Reflection on personal_belief;
Humans->Village on fission/migration_decision; Innovation->Village on
ontology_evolution (both branches) and composite_entity. Deliberately
skipped, each with a documented reason: chronicle/documentary/musing
(pure narration), culture_digest/institution_culture (reflexive
digests), caravan (no clear recipient), dream (shares omen/
consciousness's Phase G ambiguity discipline — its own docstring says
so), memory_drift/record/mind-retry/noncore_nudge/letter (per-agent
jobs judged narrower than personal_belief, kept out to avoid an
arrow-per-per-agent-job precedent). Total B4 arrows now 24. Full
detail: CHANGELOG.md's [1.34.20] entry.

Verified: `ast.parse()` clean, indent-consistency scan across every
`_send_pillar_message` site, a variable-scope sanity scan,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical,
a 4000-tick LLM-disabled soak + round-trip, and direct production-
path smoke tests for tradition/personal_belief/ontology_evolution's
merge branch.

This closes out attention-budget arbitration and inbox/outbox
coverage decisions for Tier 0's mirror sites. Remaining genuinely
open: per-agent cognition's own volume-safe design — the practical
ceiling of this pattern; anything past it needs a new design.

## Current state (v1.34.19)

Explicit user instruction: "Continue with next milestone" — following
directly off v1.34.18's own "Next Milestone" note. Three more real
B4 inbox/outbox arrows, chosen for genuine content value rather than
mechanical coverage: Village->Reflection on `rule_propose` (a rule
that survived the counterfactual sandbox is a real self-modification
event), a third Village->Humans on `religion` (a crystallized faith
is a belief-shaping fact about specific living people), a second
Reflection->Village on `self_tuning` (a genuinely applied governor
adjustment, distinct from `self_tuning_advisory`'s existing `theory`
arrow). `omen` deliberately skipped — the v1.34.9 "ignore Phase G for
this one completely" decision was scoped to one `world_model` mirror,
not a blanket license for B4 messaging too. Total B4 arrows now ten.
Full detail: CHANGELOG.md's [1.34.19] entry.

Verified: `ast.parse()` clean, indent-consistency scan over every
`_send_pillar_message` site, `scripts/verify_native_soak.py` (2 seeds
x 800 ticks) byte-identical, a 4000-tick LLM-disabled soak + round-
trip, and direct production-path smoke tests for all three new
arrows (`rule_propose` through its real sandboxed closure, `religion`
with a forced `forms: true` result, `self_tuning` with a seeded
supported hypothesis) — all three confirmed populating the correct
outbox/inbox pair.

Still open: 28 of the 34 attention-scaled sites have no matching
inbox/outbox arrow; per-agent cognition remains the one deliberately-
unmirrored Tier 0 gap.

## Current state (v1.34.18)

Explicit user instruction: "Extend to other sites" — following
directly off v1.34.17's "still fully open" note (attention-budget
arbitration and inbox/outbox participation for Tier 0's ~39 mirror
sites). Closes the attention-budget half: all 34 settlement jobs that
used the flat `_settlement_job_backpressured()` gate now call
`_pillar_interpret_backpressured(pillar)` instead, mapped per job to
its owning pillar — a pure expression swap at each site, not an
insertion, so it carries none of the indentation/scope risk the
previous slice's `_append_emergence` insertions did. Also adds three
new B4 inbox/outbox arrows chosen for real content value: Innovation
->Reflection on `invention`, Nature->Innovation on `species_variant`,
a second Village->Humans on `faction` — seven B4 arrows total now.
Full detail: CHANGELOG.md's [1.34.18] entry.

Verified: `ast.parse()` clean, an indent-consistency scan over every
`_send_pillar_message` site, `scripts/verify_native_soak.py` (2 seeds
x 800 ticks) byte-identical, a 4000-tick LLM-disabled soak + round-
trip, and direct production-path smoke tests confirming `invention`/
`species_variant` fire through their real unpatched gate and
correctly populate the new arrows.

Still open: 31 of the 34 attention-scaled sites have no matching
inbox/outbox arrow yet; per-agent cognition remains the one
deliberately-unmirrored Tier 0 gap.

## Current state (v1.34.17)

Explicit user instruction: "Extend to 45 tier 0 sites" — directly
following v1.34.16's own "deliberately NOT attempted this pass" note.
Applied the same `_append_emergence` observe/interpret-cycling
mirror to the remaining ~39 Tier 0 mirror sites across all five
pillars (village/humans/innovation/nature/reflection jobs — see
CHANGELOG.md's [1.34.17] entry for the full site list). Two real
bugs caught and fixed while applying this mechanically across so
many sites (both via independent post-hoc verification, not trusted
from the applying script's own output): a `beliefs`-job indentation
bug that would have de-scoped a downstream B4 message block, and a
`rule_propose` bug that placed the new call OUTSIDE the `async def
_sandbox_and_register()` closure it needed to be inside — referencing
an out-of-scope `rule` variable (`NameError` on every real firing)
and bypassing the counterfactual-sandbox safety gate. Full detail:
CHANGELOG.md's [1.34.17] entry.

Verified: an automated indent-consistency scan across every
`_append_emergence` site (0 real mismatches after the fixes);
`ast.parse()` clean; direct production-path smoke tests including
ones specifically targeting both fixed bugs (`rule_propose` firing
end-to-end through the real sandboxed closure, `beliefs`' new-belief
branch firing correctly on its real `interpret` turn);
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical;
a 4000-tick LLM-disabled engine soak plus a full round-trip, clean.

Still fully open: attention-budget arbitration and inbox/outbox
participation for these ~39 sites (this slice only extended
observe/interpret cycling, per the literal request).

## Current state (v1.34.16)

Explicit user instruction: "Start observe/interpret cycling,
attention-budget arbitration, and inbox/outbox participation." Root
gap: every Tier 0 mirror writes directly into `pillar.world_model`/
`memory`, bypassing `_pillar_observe_turn` (which only reads `World.
emergence_log_recent()`, never populated by Tier 0 mirrors) — so that
content never competed for bounded pillar attention or reached
inter-pillar messaging. First slice, 5-6 concrete sites (same "one
real representative site" discipline as every earlier B2/B3/B4 pass):
`guild_founding`/`fission`/`composite_entity`/`species_variant`/
`self_tuning_advisory` now also call `_append_emergence`, pillar-
tagged (observe/interpret cycling); `town_brain` now uses
`_pillar_interpret_backpressured("village")` instead of flat
backpressure (attention-budget arbitration); a new Reflection ->
Village `theory` message arrow fires on `self_tuning_advisory`
(inbox/outbox), verified end-to-end through a real `_pillar_observe_
turn` delivery. Deliberately not extended to the other ~45 Tier 0
sites — mechanical repetition, not a new design question.

Verified: all six changes confirmed via direct production-path smoke
tests including a full B4 round-trip; a 4000-tick LLM-disabled engine
soak; `scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-
identical. Full detail: CHANGELOG.md's [1.34.16] entry.

## Current state (v1.34.15)

Explicit user instruction: "Continue tier 0." Final audit slice:
`_apply_pending_dialogue_results`'s `is_llm` branch mirrors into
Humans' memory — volume-safe by construction, since `is_llm` can only
ever be the one dedicated voice pair since v1.4.0's redesign. Humans
11 -> 12. Coverage now: Innovation=5, Village=22, Humans=12, Nature=3,
Reflection=6.

Corrected a stale note in v1.34.14's own changelog: `self_tuning`'s
numeric-nudge path was already mirrored (Tier 0's first slice), not
still open as previously described.

Audited, not mirrored: per-agent cognition — the one real remaining
gap, but mirroring it wholesale would flood the bounded pillar
`memory` FIFO with daily per-agent noise; needs its own scoped design
(a volume gate cognition doesn't have today) before attempting. This
is the practical ceiling of "mirror an existing job's output."

Verified: the new mirror confirmed via a direct production-path smoke
test; a 4000-tick LLM-disabled engine soak; `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical. Full detail:
CHANGELOG.md's [1.34.15] entry.

## Current state (v1.34.14)

Explicit user instruction: "Continue tier 0 with many steps at once
and ask about consciousness." Six real jobs mirrored: `away_digest`/
`chronicler` -> Village (memory-only); `mind`/`rumor_interpret` ->
Humans (memory-only, `mind` gated to a genuine non-fallback answer
only); `self_tuning_advisory` -> Reflection (`world_model` hypothesis
+ memory). `consciousness`: asked via `AskUserQuestion` (mirror-with-
content / occurrence-only / leave unmirrored); explicit answer
"Mirror into Reflection, hypothesis-only" — implemented with real
`kind`/`detail` content, justified since Reflection's world_model/
memory sit at the same dev-console-only depth `consciousness_
intervention_log` already has; the one player-visible `_log` line
stays exactly as vague as before. `sim_summary` deliberately skipped
(restates stats other mirrors already cover).

Coverage now: Innovation=5, Village=22, Humans=11, Nature=3,
Reflection=6 — closes out nearly every `_schedule_llm_job` site
reachable by the mirroring pattern; what remains is observe/interpret
cycling, attention-budget arbitration, and inbox/outbox participation,
not more mirrors.

Verified: all six mirrors confirmed via direct production-path smoke
tests; a 4000-tick LLM-disabled engine soak; `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical. Full detail:
CHANGELOG.md's [1.34.14] entry.

## Current state (v1.34.13)

Explicit user instruction: "Continue tier 0 with many steps at once"
— second multi-job batch, twelve real jobs mirrored in one pass.
Village pillar 11 -> 20 (`naming`/`culture_digest`/`town_brain` ->
`world_model` observation; `tradition`/`folklore`/`legend_detection`/
`institution_culture`/`caravan`/`diplomacy` memory-only). Humans
pillar 7 -> 9 (`personal_belief`/`record`/`fission`, all memory-only).
Coverage now: Innovation=5, Village=20, Humans=9, Nature=3,
Reflection=4.

Verified: all twelve mirrors confirmed via one combined direct
production-path smoke test; a 4000-tick LLM-disabled engine soak;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.
Full detail: CHANGELOG.md's [1.34.13] entry.

## Current state (v1.34.12)

Explicit user instruction: "Continue tier 0 but do many steps at
once" — first multi-job batch instead of the usual one-or-two-per-
pass cadence. Village pillar 5 -> 11 real wired jobs (`chronicle`/
`documentary`/`festival` memory-only; `religion`/`faction`/`guild_
founding` -> `world_model` observation + memory, each a real settled
civic/social/institutional fact). Humans pillar 5 -> 7 (`letter`/
`noncore_nudge`, both memory-only). Coverage now: Innovation=5,
Village=11, Humans=7, Nature=3, Reflection=4.

Verified: all eight mirrors confirmed via one combined direct
production-path smoke test (found and worked around two real test-
harness gaps, not product bugs — see CHANGELOG.md's [1.34.12] entry
for detail); a 4000-tick LLM-disabled engine soak; `scripts/verify_
native_soak.py` (2 seeds x 800 ticks) byte-identical.

## Current state (v1.34.11)

Explicit user instruction: "Continue tier 0." Innovation's fifth
wired job (`era_branch` -> `world_model` observation + memory — the
branch lean is a real, already-computed decision by the time the
narration-only LLM call fires) and Reflection's fourth wired job
(`musing` -> memory-only). Nature re-checked for a fourth candidate;
none found — every remaining unmirrored job belongs to another
pillar's domain. Coverage now: Innovation=5, Village=5, Humans=5,
Nature=3, Reflection=4.

Verified: both mirrors confirmed via direct production-path smoke
tests; a 4000-tick LLM-disabled engine soak; `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical. Full detail:
CHANGELOG.md's [1.34.11] entry.

## Current state (v1.34.10)

Explicit user instruction: a direct question ("Nature can have some
many things though like ecology, forests, wildlife, geography are
they there?") followed by "Scope that out and continue tier 0."

Continue tier 0: Village's fifth wired job (`laws` -> `world_model`
observation + memory, same treatment `rule_propose` gets) and Humans'
fifth wired job (`skill_mastery` -> memory-only). Caught and fixed a
real closure late-binding risk in `_maybe_schedule_skill_mastery`'s
existing `apply()` (`skill` wasn't captured as a default argument like
its siblings). Coverage now: Innovation=4, Village=5, Humans=5,
Nature=3, Reflection=3.

Nature question, answered directly: geography naming is fully
procedural/zero-LLM; `nature_mind.py` already reads real wildlife/
climate/scar Body state, but only via one general seasonal belief-
revision pass, never a reaction to one specific ecological event.
Scoped (docs-only, docs/ROADMAP-2026-07-REMAINING.md's Tier 0
section) a new reactive `_maybe_schedule_nature_causal_reasoning`-
shaped job — grounded in one specific anomaly (wildlife local
extinction, disaster-scar spike, or stalled forest succession),
writing a `status="hypothesis"` belief plus a `world.ontology.
CausalThread` entry, `critical=True`. Not implemented; build only on
future explicit direction naming it.

Verified: both mirrors confirmed via direct production-path smoke
tests; a 4000-tick LLM-disabled engine soak; `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical. Full detail:
CHANGELOG.md's [1.34.10] entry.

## Current state (v1.34.9)

Explicit user instruction: "continue tier 0" + a direct answer to a
question raised about Nature's stuck-at-2-jobs status. Asked via
`AskUserQuestion` whether `omen` (the best content fit for a Nature
third job) should mirror into `nature_pillar.world_model` despite
Phase G's "never confirm anything supernatural" discipline — user
answered "ignore phase G for this one completely." `_maybe_schedule_
omen` now mirrors as a `status="hypothesis"` (never `"observation"`)
entry, scoped to this ONE mirror site only — every other omen
consumer (stat tile, dev console, narration) stays exactly as
ambiguous as before; Phase G's discipline is otherwise unchanged
everywhere else. Nature now at 3 jobs. Verified via a direct
production-path smoke test (temperament pushed high, driven through
real gating conditions until it fired) plus a clean 4000-tick soak.
Full detail: CHANGELOG.md's [1.34.9] entry.

## Current state (v1.34.8)

Explicit user instruction: "continue tier 0." `_maybe_schedule_
composite_entity` (a real standing building named + given an origin
story, backed by a genuinely new registered `InventedConcept`) now
mirrors into `innovation_pillar.world_model` as an `observation`,
same treatment `invention`/`ontology_evolution` already get.
Innovation now at 4 jobs. Verified via a direct production-path
smoke test plus a clean 3000-tick soak. Full detail: CHANGELOG.md's
[1.34.8] entry.

## Current state (v1.34.7)

Explicit user instruction: "continue with tier 0." A fourth real
production job (`memory_drift`) now mirrors into Humans pillar's
`memory` — memory-only, same shape as `dream`/`migration_decision`.
Humans now at 4 jobs. Re-checked Nature for a third candidate again;
`omen` is the closest by content but sits under Phase G's ambiguity
discipline (its own docstring: never confirm anything supernatural),
which a pillar `world_model` entry's `observation`/`hypothesis`
status would violate — left unmirrored. Verified via a direct
production-path smoke test (a real core-cast agent's memories via
`_remember`, the job driven through its real gating conditions until
it fired) plus a clean 4000-tick soak. Full detail: CHANGELOG.md's
[1.34.7] entry.

## Current state (v1.34.6)

Explicit user instruction: "continue with tier 0." A third real
production job now mirrors into each of Reflection and Village's
pillar state — `reflection_question` -> Reflection (memory-only, now
3 jobs), `rule_propose` -> Village (`world_model` observation +
memory, now 4 jobs). Found and fixed a real pre-existing bug while
verifying: `_musing_subject()` picked the newest open `reflection_
notebook` entry without filtering by `kind`, so a `"question"` entry
(`confidence=None` by design) could reach `llm/musing.py`'s prompt
builder and crash formatting `None` as a float — now filtered to
`kind == "hypothesis"`, matching the method's own stated intent.
Verified via direct production-path smoke tests for both new mirrors
plus the exact crash repro (confirmed fixed), and a clean 4000-tick
soak. Nature stays at 2 jobs — no obvious third candidate found.
Full detail: CHANGELOG.md's [1.34.6] entry.

## Current state (v1.34.5)

Explicit user directive, docs-only: the world map should visually
communicate history rather than reading as a static procgen map with
agents on top. Filed as docs/VISION-2026-07-24-LIVINGMAP.md (M1-M12);
docs/ROADMAP-2026-07-REMAINING.md gained a new Tier 1.5, sequenced
after Tier 1 (several of the biggest items — real erosion/flooding-
reshapes-terrain, rivers re-carving — are blocked on A11's own
already-recorded mutable-elevation item) and before Tier 2. Cross-
referenced against real existing coverage (the four scar-shaped
overlays, the "🗺️ fields" toggle, layout/architecture/dialect
grammar) rather than treated as greenfield; confirmed by direct code
check that a fully-decayed road leaves no persistent trace today
(`RoadNetwork.wear` deletes the position on full decay). Also
recorded the standing philosophy itself in CLAUDE.md's Observatory UI
direction section directly, not just the vision doc. Full detail:
CHANGELOG.md's [1.34.5] entry.

## Current state (v1.34.4)

Explicit user request, docs-only: fold ten live-diagnostic findings
(Reflection/Nature pillar cadence, LLM call-volume/reasoning-tier
audits, rule-generation malformed JSON, social scaling, cumulative-
culture strengthening, belief life cycle, cognition-level "why"
diagnostics, long-horizon memory consolidation) into the roadmap as a
new Tier 0.5 (right after Tier 0, before Tier 1) — cheaper/more
urgent than Tier 1's substrate work, and each carries an explicit
user hard-stop: no change may degrade cognition/sentience quality.
D1/D2 cross-reference v1.23.1's prior "cold-start latency, not a bug"
diagnosis for re-investigation (this new report describes a much
longer run with the same symptom). D5 confirmed as a real gap:
`rule_proposal` has no `json_schemas.py` entry, unlike FT.0's eleven
covered tasks. Full detail: CHANGELOG.md's [1.34.4] entry.

## Current state (v1.34.3)

Explicit user request, docs-only: fold an uploaded checklist
(HearthBench model-selection benchmark + the Adaptive Runtime
execution layer) into the current roadmap, ordered to run after the
previous roadmap items. Filed verbatim as docs/HEARTHBENCH-RUNTIME-
2026-07-23.md (same convention as docs/MASTERCHECKLIST-2026-07-
22.md); docs/ROADMAP-2026-07-REMAINING.md gained a new Tier 5
pointer section preserving the source doc's own two-track SEQUENCE
rather than re-deriving one. Sequenced strictly after Tiers 0-4 with
explicit rationale (infrastructure for building/measuring Hearthmind,
not a Hearthmind feature — building it before Body/Mind/Seam work
stabilizes means re-benchmarking against a moving target). Full
detail: CHANGELOG.md's [1.34.3] entry.

## Current state (v1.34.2)

Explicit user instruction: "expand A9 further... completely close
it." Fixed the one remaining real gap: `pattern_signal_counts[
"materials_bottleneck"]` had a plain-language label (`llm/ontology.
py`) but no writer anywhere — `_detect_settlement_bottlenecks`'s
existing edge-trigger now increments it. Also corrected two of
v1.34.0's own findings on re-examination: `architecture_grammar`'s
descriptor and `causal_threads` are deliberately UI-facing flavor by
their own design docs, not abandoned producers; `Agent.genome` is
already a genuine closed producer+consumer loop (birth -> `Agent.
traits`) — "never revised post-conception" isn't a gap, it's correct
biology (the codebase's own `hardened_traits` mechanism already
covers "life permanently reshapes behavior" at the phenotype layer,
which is where it belongs). `Settlement.legends`' write-only status
stands, already tracked under A21's own roadmap entry, not A9's. Full
detail: CHANGELOG.md's [1.34.2] entry. This closes A9.

## Current state (v1.34.1)

Explicit user instruction: "do the second pass" — closes v1.34.0's
own loudest flagged finding. `world/spatial_memory.py`'s `location_
character` split into `location_character_from_dicts(...)` (the real
logic) + a thin `World`-scoped wrapper; `Population._choose_build_
site`'s mining/disaster/ruin scoring now reads from ONE call to the
former instead of three duplicate `.get()` lookups — the read-side
unification A19 built is now genuinely used, not a still-dead
sibling. Behavior unchanged. Residual, honestly flagged: the `World`-
scoped `location_character(world, x, y)` wrapper itself still has no
caller (nothing with `World` in scope needs it yet) — a future
dialogue/cognition/NPC-inspector consumer is the natural next step,
not attempted. Full detail: CHANGELOG.md's [1.34.1] entry.

## Current state (v1.34.0)

Explicit user instruction: "tier 1 - 1" — A9 feedback-loop audit
(docs/ROADMAP-2026-07-REMAINING.md's Tier 1 item 1). Checked 15 named
state stores for a real producer+consumer pair; most already closed,
two real write-only producers found and fixed (`World.mining_scars`/
`disaster_scars` now bias `Population._choose_build_site` away from
badly scarred ground, same shape as `ruin_scars`' existing positive
pull, new `MINING_SCAR_SITE_PENALTY_SCALE`/`DISASTER_SCAR_SITE_
PENALTY_SCALE`). Four more real gaps recorded (not fixed this pass):
`spatial_memory.location_character()` itself unused, `architecture_
grammar`/`Settlement.legends` display-only, `materials_bottleneck`
pressure label with no writer, `Agent.genome` write-once-at-birth
only. **Also surfaced, unrelated to this pass's own change**: `scripts/
verify_native_soak.py` (2 seeds x 1500 ticks) shows a pre-existing
MISMATCH at tick 1055 on unmodified `origin/claude/hearthmind-
overview-5bekay` — confirmed via `git stash` before/after comparison,
so it predates this session's work and is a real open native/fallback
divergence worth its own diagnostic pass, not yet root-caused. Full
detail: CHANGELOG.md's [1.34.0] entry.

## Current state (v1.33.0)

Explicit user instruction: "continue with tier 0." Directly extends
v1.32.0: a THIRD real production job now mirrors into each of four
pillars' `world_model`/`memory` — ontology_evolution -> Innovation
(both merge/evolve branches), species_variant -> Nature, dispute ->
Village (memory-only, every outcome), migration_decision -> Humans
(memory-only). Coverage now 2-3 jobs/pillar (was 1-2). Verified via
direct production-path smoke tests (fake LLM client through each
job's real gating conditions) plus a clean 3000-tick soak. Full
detail: CHANGELOG.md's [1.33.0] entry.

## Current state (v1.32.0)

Explicit user instruction: "start with tier 0" (docs/ROADMAP-2026-07-
REMAINING.md's top item — B1/B2/B3/B7 each shipped on the strength of
one representative job per pillar; ~50 other LLM call sites untouched
by the pillar abstraction). First slice only (the full refactor is
too large for one batch, per the roadmap's own note): one additional
real production job per pillar now mirrors into that pillar's `world_
model`/`memory` — invention -> Innovation, self_tuning -> Reflection
(applied nudges only), institution_belief -> Village, dream -> Humans
(memory-only, deliberately no world_model entry — a dream is symbolic
content, not a collective theory). Doubles wired coverage from 1 to 2
jobs/pillar. Verified via direct production-path smoke tests (fake
LLM client driving each job's real gating conditions) confirming
correct world_model/memory writes, plus a clean 4000-tick soak. Full
detail: CHANGELOG.md's [1.32.0] entry.

## Current state (v1.31.0)

Explicit user request: "audit the master checklist deep pass and see
if there is anything else you have left out to implement and add that
to roadmap too." Full detail: CHANGELOG.md's [1.31.0] entry.

Verified `docs/ROADMAP-2026-07-REMAINING.md` covers all 39 Master
Checklist items (25 Body + 9 Mind + 5 Seam) 1:1, and every "remain
open"/"not attempted"/"not built" note in the source doc traces back
to something already recorded — nothing missing. Two minor findings
added as an "Addenda" section: A11's hydrology R7-deferral is
justified differently than its neighbors (new-mechanism-needs-
validation, not low-density); the Master Checklist's own footer never
got updated to reflect that B7's "open design decision" was in fact
resolved (by adopting the doc's own stated default) when step 14
shipped in v1.12.0 — a documentation loose end in the source doc, not
a code gap. Docs-only.

## Current state (v1.30.0)

Explicit user follow-up: "add items from part B and C too why did you
not include it in the roadmap?" — fair pushback on v1.29.0's own scope
call (excluding B/C was my judgment, not requested). Full detail:
CHANGELOG.md's [1.30.0] entry.

`docs/ROADMAP-2026-07-REMAINING.md` extended with Part B (B1-B9)/Part
C (C1-C5). Headline finding: B1/B2/B3/B7 are each "shipped" on the
strength of exactly one representative job per pillar — the other ~50
LLM call sites remain untouched by the pillar abstraction. New **Tier
0** names this as the single biggest lever in the document, bigger
than any Part A item. Other real gaps recorded: B4's one-sided
disagreement check, B5's now-unblocked affordance/reaction query
(Stage IV shipped since B5's deferral), B8's missing reinforce/
reinterpret, C2's mostly-unbuilt intention coverage, C3's "pillars
initiate contact," C4's missing runtime auditor. B9 noted as
effectively closed (covered by B4).

## Current state (v1.29.0)

Explicit user request, docs-only: "build an updated roadmap to
implement all the features from all parts that you deferred for later
and did not implement in the first pass. This includes porting to
C++ as well." New `docs/ROADMAP-2026-07-REMAINING.md` — every "still
open"/flagged item across Part A's 25 det_sys.md items (docs/
MASTERCHECKLIST-2026-07-22.md), plus the R7 C++-porting backlog,
extracted close to verbatim from that doc so it stays a faithful
snapshot rather than a paraphrase that could drift. Includes a 4-tier
priority ordering (substrate items first — A9's feedback-loop audit,
A11's hydrology/erosion, A1's remaining fields, A2's diffusion
operators — down to standing-discipline re-audit items A23-25).
Explicit scope note in the doc itself: Part B/C and other vision docs
are NOT re-swept (per CLAUDE.md's own record, substantially shipped
already) — filed with that scope stated up front rather than assumed,
since a broader sweep was a real option not silently declined.

## Current state (v1.28.0)

Explicit user instruction: "Start A21." Full detail: CHANGELOG.md's
[1.28.0] entry. `Settlement.folklore` had no structured subject to
detect legends against — resolved by building a separate pipeline off
A22's Emergence API stream instead (`World.emergence_log`, already
carries a real `subsystem` tag + `settlement` name). New `world/
legends.py`'s deterministic `detect_legend_candidate` (N repeated
same-subsystem observations for a settlement, zero LLM cost most
months) → `llm/legend.py`'s LLM narration → new `Settlement.legends`
(capped, one-legend-per-subsystem-lifetime). New monthly engine job,
same shape as folklore. UI: "Legends" panel, 🐉 event icon. **Closes
Stage IV** — all 16 originally-scoped roadmap steps now have at least
a first slice. Legend→tradition/institution feedback and folklore
unification remain open, flagged.

## Current state (v1.27.0)

Explicit user instruction, follow-up to a live report ("I can't see
the hydrology implementation... are they visible on the live map
itself?"): "finish stage 4 and implement all part A items to be
visible on the live map itself. The map should change and evolve with
the simulation — that was the whole point." Full detail: CHANGELOG.md's
[1.27.0] entry.

Root gap: hydrology moisture, soil fertility, and A1's population-
density field were all real backend state with zero (or stat-tile-
only) map representation. New toggleable "🗺️ fields" header button
cycles a live heatmap directly on the map canvas (moisture/soil-
fertility/population-density) — piggybacks on the existing terrain-
resync channel plus a new `week_end`-triggered resync and a 20s
client-side periodic re-fetch, since none of these three fields fire a
`TERRAIN_CHANGING_CATEGORIES` event of their own. A20 "Multi-scale
aggregation" (Stage IV step 29) extended in step: `population_density`
gained a second real, independent consumer (`MIGRANT_DENSITY_
DAMPENING` dampens migrant draw at an already-crowded region) beyond
its original sole fission-site-avoidance consumer. A21 "Temporal
compression pipeline" (step 30) explicitly NOT attempted — audited and
flagged (`Settlement.folklore` has no structured subject field to
detect legends against without a fragile heuristic; needs its own
follow-up first). This closes Stage IV's originally-scoped 16 steps
(one, A21, explicitly deferred with reason, not silently skipped).

## Current state (v1.26.0)

Explicit user instruction: "next step" — A3/A4 "Continuous procgen +
scripted-event conversion," first slice (roadmap Stage IV step 28,
docs/MASTERCHECKLIST-2026-07-22.md). A3's own worked example: "ruins
should form where settlements die." Full detail: CHANGELOG.md's
[1.26.0] entry.

Root gap: `RUIN_REMOVAL_TICKS=1200` deleted a fully-decayed building
with zero persistent trace. New `World.ruin_scars` (`world/terrain_
evolution.py`, same scar-shaped-dict pattern as `mining_scars`/
`disaster_scars`/`ritual_activity`, by far the slowest-decaying of the
four — ~1.6 years to fully clear) gained at both building-removal code
paths in `Settlement.tick`. Real consequence: `Population._choose_
build_site` now biases toward a tile with a prior ruin — "the village
rebuilds on old foundations." Added as a 4th axis to A19's `location_
character` unification. Rivers/erosion (mutating immutable, native-
store-backed `Tile.elevation`) and A4's economy/agriculture/
information continuous-field conversion remain explicitly open,
flagged. UI: new "Ruins" stat tile, map overlay, bare-tile inspector
line.

## Current state (v1.25.0)

Explicit user instruction: "next step" — A7 "Grammar-based procedural
systems," first slice (roadmap Stage IV step 27, docs/MASTERCHECKLIST-
2026-07-22.md). This item's own checklist flagged a design decision
needed first; resolved via `AskUserQuestion` — accepted the doc's own
default split (layout/architecture/dialect deterministic, myth/custom/
law stay LLM) and, per explicit user answer ("do everything"), shipped
all three domains in one batch rather than the usual one-domain-at-a-
time slice. Full detail: CHANGELOG.md's [1.25.0] entry.

New `world/dialect_grammar.py` (rewrite rules over an existing LLM-
coined term — a fissioning daughter settlement inherits a few of its
origin's terms, each drift-mutated), `world/layout_grammar.py` (a
settlement's stable radial/linear/clustered style biases the existing
build-site scoring), `world/architecture_grammar.py` (a deterministic
per-building-instance structural descriptor). None is a full rewrite/
graph/shape grammar — each is a scoped-down first slice over existing
mechanisms, flagged. UI: "Layout" stat tile, building-inspector
"Character" line.

## Current state (v1.24.0)

Explicit user instruction: "next step" — A19 "Persistent spatial
memory," first slice (roadmap Stage IV step 26, docs/MASTERCHECKLIST-
2026-07-22.md). Full detail: CHANGELOG.md's [1.24.0] entry.

New `World.ritual_activity` (fourth per-tile scar-shaped dict, same
additive-overlay/weekly-decay pattern as `mining_scars`/`disaster_
scars`), gained when a shrine-boosted festival happens on a tile. New
`world/spatial_memory.py`'s `location_character(world, x, y)` is the
real read-side unification A19 calls for — one query over mining/
disaster/ritual, not three independent lookups; the spec's other six
named axes (traffic/pollution/fertility/ownership/construction/
ecology) remain open, flagged. Real consequence: a shrine that's
hosted a festival before amplifies the next one held there ("a ritual
site draws ritual," scoped to magnitude). UI: new "Ritual sites" stat
tile, map overlay, SHRINE inspector line.

## Current state (v1.23.1)

Explicit live report: "Nature and especially Reflection still feel
disconnected... not forming any hypothesis even after 13k ticks."
Diagnosed — B2's observe/interpret halving means the first real
output needs 2 boundaries (Nature: ~17.5k ticks; Reflection: ~70k
ticks), invisible cold-start latency, not a bug. Explicit user
decision: don't change the cadence, just make it visible. Full
detail: CHANGELOG.md's [1.23.1] entry.

New `Pillar.turns_processed` + `SimulationEngine._pillar_cognition_
status()` (on-demand `full_diagnostics()` only — the pattern-detector
read is too heavy for per-tick). New dev-console "Pillar cognition
status" panel (real formatted text, not raw JSON), populated on "Full
diagnostic report."

## Current state (v1.23.0)

Explicit user instruction: "Next step" — A18 "Events as composable
reactions," first slice (roadmap Stage IV step 25, docs/MASTERCHECKLIST
-2026-07-22.md). Full detail: CHANGELOG.md's [1.23.0] entry.

New `world/reactions.py` + `SimulationEngine._maybe_tick_composite_
reactions`: a general AND-combination reaction engine, distinct from
`TriggerRule` (single trigger, LLM-authored) — the engine is fixed and
general, one hand-authored `CompositeReaction` ("Desperate Times":
`drought` + `feud` + `food_shortage` crossing simultaneously) proves it
works. Consequence: the two feuding families' relationships take a
real, bounded, immediate hit, plus an Emergence API entry. The doc's
own "raid" example is scoped down to this relationship-rupture
consequence rather than a new combat mechanic. A real authoring system
for new combinations remains open, flagged. UI: new event icon (💥) +
filter-group mapping.

## Current state (v1.22.0)

Explicit user instruction: "Next step" — A17 "Information ecosystem
unification," first slice (roadmap Stage IV step 24, docs/
MASTERCHECKLIST-2026-07-22.md). Full detail: CHANGELOG.md's [1.22.0]
entry.

New `world/memetics.py`: a reusable social-graph propagation weight
(`weighted_spread_target`/`propagation_weight`) — "who catches this
next" now traces real fondness/trust ties (Phase 0's `Ledger`) instead
of uniform random selection. Real production proof: ontology concept
adoption spread (`_maybe_spread_concepts`) now spreads preferentially
to people close to an existing adopter. Scoped deliberately narrow —
this is the propagation-weight primitive a full A17 unification would
need, not the unification itself; folding rumor/tradition/belief/song/
technique onto it, plus a shared mutate/decay/compete step and a
fitness-vs-truth axis for rumors, remain open, flagged. No UI change
this pass (a selection-algorithm change, not new exposed state).

## Current state (v1.21.0)

Explicit user instruction: "Next step" — A14 "Layered organism
biology," first slice (roadmap Stage IV step 23, docs/MASTERCHECKLIST-
2026-07-22.md), the spec's own worked example ("immune response as
state, not a coin flip"). Followed by an explicit mid-turn user
request: "All these new features should appear in the live map of UI
as well, expose them to UI" — addressed same batch. Full detail:
CHANGELOG.md's [1.21.0] entry.

New `Agent.immune_strength` (continuous 0..1, plain Python-side):
drifts toward a nutrition/rest-derived target each tick (exponential
smoothing — real physiological lag), drains further while actively
sick (reverse coupling). Modulates (never replaces) disease
transmission/death-chance rolls, centered so the neutral baseline is a
true no-op against every existing tuned rate. Scoped to the one named
subsystem (immune response); stress/reproduction/development/injury-
recovery/sleep remain open, flagged.

UI exposure pass across steps 18-23: `World.summary()` (the regular
broadcast) gained a real per-settlement `discoverable` field (same
A5/A6/A12/A13 query Innovation's prompt uses) + a "Discoverable" main-
UI stat tile; agent map markers gained a third status ring (faint
amber, low immune_strength but not sick/immune); NPC inspector gained
plain-language immune-state readings. Genetics (A15)/evolutionary
innovation (A8) confirmed already reaching real UI from their own
passes — no gap found there.

## Current state (v1.20.0)

Explicit user instruction: "Next step" — A15 "Genetic inheritance,"
first slice, scoped to humans (roadmap Stage IV step 22, docs/
MASTERCHECKLIST-2026-07-22.md). Full detail: CHANGELOG.md's [1.20.0]
entry.

Replaces v0.87.6's flat parent-average+noise trait blend with real
diploid genetics: `Agent.genome: dict[trait, (allele_a, allele_b)]`
over the four existing psychology axes; `Agent.traits` (unchanged
meaning, every consuming call site untouched) is now the mean of its
two alleles. `Population._inherited_genome_and_traits` does real
Mendelian-style inheritance — each child allele independently drawn
from a randomly-chosen one of that parent's own two alleles (drift),
each independently subject to `GENOME_MUTATION_CHANCE` of a fresh
mutated value instead (mutation). Founders now draw a real diploid
genome at spawn (`seed_founder_genome`) — every prior founder started
flat 0.0 on all four axes; this closes that gap as a verified side
effect. Natural selection needed no new code — these traits already
causally affect survival/reproduction (H6), so genetics just gives
that pre-existing pressure a real heritable substrate. Scoped to
humans only; wildlife/animal genetics and A14 (physiological genes)
remain open, flagged. NPC inspector gained a "mixed inheritance" line
reading real allele divergence.

## Current state (v1.19.0)

Explicit user instruction: "Next step" — A8 "Evolutionary Innovation
loop," first slice (roadmap Stage IV step 21, docs/MASTERCHECKLIST-
2026-07-22.md). Full detail: CHANGELOG.md's [1.19.0] entry.

`world/ontology.py` already had propose/evolve/merge with lineage
(generate); this pass adds real evaluate + select. `evaluate_fitness`:
mean `Population.reputation` of a concept's living adopters vs. its
settlement's living-population mean ("did adopters prosper?").
`run_selection` (same monthly cadence as `abandon_stale`): sustained
unfitness over `FITNESS_EVALUATION_MIN_READINGS` readings retires a
`spreading`/`established` concept to a new `"retired"` status (distinct
from `abandoned`), revising Innovation's mirrored belief the same way
`abandon_stale` already does. `_maybe_schedule_ontology_evolution`'s
evolve/merge parent pick is now fitness-WEIGHTED (`fit_established_
concepts`/`concept_fitness_weight`, floored so no established concept
is ever categorically excluded) instead of flat-uniform. New
`InventedConcept.generation` (0 original, `max(parents)+1` evolved/
merged) threaded through `register_concept`. Sandbox-forward-sim-as-
fitness and grammar-based mutation (A7) remain open, flagged. Knowledge
tree UI gained a "generation N" marker on descendant concepts.

## Current state (v1.18.0)

Explicit user instruction: "Next step" — A13 "Chemistry / reaction
system," first slice (roadmap Stage IV step 20, docs/MASTERCHECKLIST-
2026-07-22.md), continuing directly off v1.17.0's A12. Full detail:
CHANGELOG.md's [1.18.0] entry.

New `world/chemistry.py`: the doc's own three worked examples over
A12's real registry — clay+heat→ceramic, ore+heat→metal, fiber+
water_and_time→cured_fiber (fiber tanning/curing). `world/materials.py`
gained the three product materials (`ore`/`ceramic`/`cured_fiber`) as
real, fully-propertied entries. `discover_reactions` is the real
"what does X produce under Y?" query — conditions are derived from the
same A5/A6/A12 affordance layer, so both the right material AND the
right standing building are genuinely required. Scoped down from the
spec's literal automatic-firing reactor (query half only this pass,
flagged follow-up). Wired into Innovation's generate-step (`llm/
ontology.py`'s new `discoverable_reactions` param) and a matching
dev-console diagnostic.

## Current state (v1.17.0)

Explicit user instruction: "Next step" — A12 "Material science /
physical properties," first slice (roadmap Stage IV step 19, docs/
MASTERCHECKLIST-2026-07-22.md), continuing directly off v1.16.0's
A5/A6. Full detail: CHANGELOG.md's [1.17.0] entry.

New `world/materials.py`: `Material` (ten spec-named 0..1 properties)
+ a small closed `MATERIALS` registry (wood/stone/clay/metal/fiber),
hand-authored with real-world-plausible relative ordering.
`BUILDING_MATERIALS` assigns each A5-tagged `BuildingKind` its primary
material. `derive_affordances(material)` is the real "properties →
affordances" bridge (hardness+workability → `can_sharpen`,
flammability → `can_burn`, etc. — deliberately partial, only the
raw-material-derived subset). `building_affordances(kind)` unions this
with A5's existing hand-tagged set (never replaces it) — wired into
Innovation's A5/A6 generate-step and the dev-console diagnostic from
v1.16.0. Per-instance `Entity.material` and A13's chemistry/reaction
system remain open, flagged. New "Built of" line in the building click
inspector.

## Current state (v1.16.0)

Explicit user instruction: "Next step" — A5/A6 "Affordances +
discovery query layer," first slice (roadmap Stage IV step 18, docs/
MASTERCHECKLIST-2026-07-22.md). Full detail: CHANGELOG.md's [1.16.0]
entry.

New `world/affordances.py`: the spec's own closed `can_X` vocabulary
hand-tagged onto `BuildingKind` (`BUILDING_AFFORDANCES`) — deliberately
wraps the existing closed/native-mirrored enum rather than touching
it. Real query layer: `affordances_present` ("what here can_X?"),
`discover_combinations` ("what combination would achieve Y?") over a
small closed `KNOWN_COMBINATIONS` registry. Real consumer:
`_maybe_schedule_ontology_proposal` grounds Innovation's proposal
prompt in genuinely-standing-building affordances (`llm/ontology.py`'s
new `discoverable_combinations` param), alongside the existing
prosperity/pressure grounding. Per-instance `Entity.affordances`/A12
material-derived properties, and the validate-step half (re-checking a
proposed concept against this layer), remain open, explicitly flagged.
New dev-console `discoverable_affordance_combinations` diagnostic.

## Current state (v1.15.0)

Explicit user instruction: "Next step" — A10 "Ecology as interacting
populations / food webs," nutrient cycling only (roadmap Stage IV
step 17, docs/MASTERCHECKLIST-2026-07-22.md). Full detail: CHANGELOG.
md's [1.15.0] entry.

New `economy/farms.apply_nutrient_cycling(farms, herds)`: any
already-farmed `FarmGrid.soil_fertility` tile within `NUTRIENT_
CYCLING_RADIUS` of a `WildlifeGrid` herd gains a small, herd-size-
scaled, per-call-capped fertility bonus — real grazing/dung
enrichment closing a loop into farming, per the roadmap doc's own
"Feeds" line. Weekly cadence (`World._tick_disasters`, same reasoning
as A11's `tick_hydrology`). Standalone, read-only-of-wildlife,
never-expands-tracked-tiles by construction, so it carries zero
native/fallback parity risk against either grid's native fast path.
Migration, competition, decomposition, pollination, habitat
formation, and folding the food web onto the A1 field substrate all
remain open, explicitly flagged in the roadmap doc rather than
silently dropped. New "Soil fertility" main-UI stat tile (`summary.
farms.avg_soil_fertility`, previously computed but unsurfaced).

## Current state (v1.14.0)

Explicit user instruction: "Next step" — A2 "CA/diffusion/reaction-
diffusion operators" (roadmap Stage IV step 16, docs/MASTERCHECKLIST-
2026-07-22.md). Full detail: CHANGELOG.md's [1.14.0] entry.

New `world/ca_operators.py`: `diffuse`/`reaction_diffuse`/`cellular_
step`, three generic pure field operators, not tied to one subsystem.
Forest succession (det_sys.md's own worked "first consumer" example):
`terrain_evolution.compute_succession_pressure` diffuses a forest-
indicator grid into a real neighborhood-density reading, averages it
against A11's moisture field (v1.13.0), and MODULATES (not replaces)
the existing `REFOREST_MIN_FALLOW_WEEKS` threshold per tile — well-
forested+moist reclaims in as few as 1 week, poor conditions take up
to 2x longer. Deliberately a bounded modulation, not a rewrite, since
`maybe_reclaim`'s chance-roll has a native fast path; the eligibility
computation this pass touches stays pure Python either way, so native/
fallback parity holds. `moisture=None` keeps old flat-rate behavior.

## Current state (v1.13.0)

Explicit user instruction: "Start Stage 4's first step" — A11
"Continuous hydrology," first slice (roadmap Stage IV step 15, docs/
MASTERCHECKLIST-2026-07-22.md). **Starts Stage IV** ("Deepen the
Body," 16 steps; 15 remain). Full detail: CHANGELOG.md's [1.13.0]
entry.

New `world/hydrology_field.py`'s `HydrologyField`: real per-tile 0..1
`moisture`, ticked weekly — precipitation gain, single-pass downhill
transfer to each land tile's lowest-elevation neighbor, evaporation
(faster in summer). Water tiles pinned saturated. Two of A11's four
named pieces deliberately deferred and flagged: groundwater (surface-
only this pass) and erosion into now-mutable elevation (`Tile.
elevation` stays immutable — the biggest remaining piece, touches the
native-ported `TerrainGrid`, needs its own equivalence pass). Real
consumers: `FarmGrid.plant()`'s yield now scales with actual local
moisture (`FARM_MOISTURE_YIELD_MIN_FACTOR=0.5` floor); `_detect_
hydrology_drought` emits an edge-triggered `nature`/`village`-tagged
Emergence API observation on a genuinely widespread drought. R7
deviation flagged (pure Python, weekly not per-tick cadence, not
natively ported) — justified as a from-scratch mechanism needing live
shape-validation before a compiled port, not a low-density excuse.
Silent backfill on legacy snapshots (not routed through `migrated_
subsystems` — background field, not a narrated genesis event). Main-
UI "Soil moisture" stat tile (plain environmental state, not Phase-G-
gated).

Per the roadmap's own scoping note that Stage IV steps are
substantially larger than Stage I-III ones, continuing to step 16 only
on explicit future direction naming it, same standing convention.

## Current state (v1.12.0)

Explicit user instruction: "Continue with next roadmap" — B7 "Humans
collective consciousness + coordinator," first version (roadmap Stage
III step 14, docs/MASTERCHECKLIST-2026-07-22.md). **Closes Stage III**
(steps 10-14 all shipped). Full detail: CHANGELOG.md's [1.12.0] entry.

Both named mechanisms already existed: `humans_pillar` IS the
collective mind (mood/values/direction, via `_maybe_schedule_
narrative_direction`, already B1-generalized); core-cast cognition +
the voice pair's narrative-significance selection IS the capped
per-NPC pool. The real gap: they ran unaware of each other. Fixed —
the voice-pair-rotation site now writes `humans_pillar.self_model[
"current_protagonists"]` directly and emits a `humans`-tagged
Emergence API observation, so a rotation reaches the collective mind's
next real `observe` turn as perceived context. Respects the doc's
standing design decision (individual acts locally, collective sets the
mood/direction measured against) — `current_protagonists` is pure
awareness, never a speaking/acting channel. Dev-console-only surfacing
(`full_diagnostics()["humans_pillar"]`) — the rotation already had
real main-UI visibility via the pre-existing `voice_pair_change` event.

## Current state (v1.11.0)

Explicit user instruction: "Continue with next roadmap" — B6
"Reflection as meta-scientist," first version (roadmap Stage III step
13, docs/MASTERCHECKLIST-2026-07-22.md). Full detail: CHANGELOG.md's
[1.11.0] entry.

`_maybe_schedule_self_tuning` used to match a supported hypothesis's
subject against `TUNABLE_GOVERNORS` by exact equality against only two
hardcoded global labels — every settlement-scoped pattern (`f"{label}
in {settlement_name}"`, five of the six `_detect_reflection_pattern`
signal families) could never match, so a real supported hypothesis
about any of them was silently dropped. New `SimulationEngine.
_governor_key_for_subject` matches by PREFIX instead; `TUNABLE_
GOVERNORS` gained `"disease outbreak" -> "disease_outbreak_chance"` as
the worked example, consumed by a new `chance_multiplier` param on
`Population._maybe_outbreak` (ordinary per-tick Python, no native-port
parity risk). A supported hypothesis that STILL names no governor now
gets a real advisory instead of silence: `World.advisory_proposals` +
`_schedule_advisory` (critical LLM call, free-text advice) + `POST
/advisory/{id}/review` (accepted/rejected, the ONLY status mutator,
never auto-applied — kept strictly out-of-band from the sandboxed
numeric self-tuning path). "Track advice outcomes" scoped as the
human's own accept/reject marking, not a further automated judgment
(no mechanical effect exists to score against). Dev-console-only
surfacing (`advisory_proposals_recent`), same depth as `self_tuning_
actions_recent`.

## Current state (v1.10.0)

Explicit user instruction: "Continue with next roadmap" — B5
"Innovation as conscious scientist," first version (roadmap Stage III
step 12, docs/MASTERCHECKLIST-2026-07-22.md). Full detail: CHANGELOG.
md's [1.10.0] entry.

`_maybe_schedule_ontology_proposal` already gated on a settlement
being "pressured" (`pattern_signal_counts` crossing `PATTERN_SIGNAL_
BELIEF_THRESHOLD`) but never told the LLM which pressure — fixed by
naming the dominant crossed signal in plain language (`llm/ontology.
py`'s new `PRESSURE_SIGNAL_LABELS`) and asking for a real `hypothesis`
field (the problem this idea might address, or "no specific problem").
`InventedConcept.hypothesis`/`world_model_entry_id` (new fields) close
the loop deterministically: `world/ontology.py`'s new `_record_
hypothesis_outcome` revises Innovation's own mirrored `world_model`
belief IN PLACE when the concept's real adoption fate later confirms
it (`established` — confidence 0.85) or refutes it (`abandon_stale`'s
existing sweep — confidence 0.1), zero added LLM cost. Scoped
deliberately against today's closed-hook vocabulary per the roadmap
item's own permission to do so — a real affordance/reaction query
waits on Stage IV, not built yet; evolve/merge untouched this pass.
Surfaced: `knowledge_tree()`'s concept entries append the hypothesis
as plain-language context in the existing 🌳 panel.

## Current state (v1.9.0)

Explicit user instruction: "Next step" — B4 "Inter-pillar consciousness
bus" (roadmap Stage III step 11, docs/MASTERCHECKLIST-2026-07-22.md).
Full detail: CHANGELOG.md's [1.9.0] entry.

`Pillar.send_message`/`receive_message` (bounded inbox/outbox, cap 8)
makes the B1-era structural message plumbing real. New `Pillar.
disagrees_with(subject_text)`: confident (`>=0.5`) same-subject
`world_model` overlap (substring or Jaccard `word_overlap()` >=0.2,
compared against short `subject` labels, not full belief sentences —
sentence-level comparison measured ~0.1 overlap on genuinely related
text during development, unreliable). `SimulationEngine._send_pillar_
message` wires three arrows at existing apply() sites: Nature->Village
(disagreement-aware: `"disagreement"`/`"warning"`/`"observation"`),
Village->Innovation (`"theory"`, confidence-gated), Innovation->Village
(`"discovery"`, every new concept). `_pillar_observe_turn` merges
undelivered inbox messages into the same magnitude-ranked candidate
pool as Emergence API observations (`_PILLAR_MESSAGE_MAGNITUDE` per-
kind table) — only delivered messages leave `inbox`, so an outranked
message persists to compete again next cycle (the actual mechanism
behind lasting disagreement, not just a flag). Reflection's own
observe-all-four-Minds arrow needed no new code (`_detect_reflection_
pattern` already reads every pillar's Body state directly).
Reverse-direction disagreement classification (Village/Innovation
checking whether the sender disagrees) flagged as follow-up — only the
Nature->Village site does it this pass.

## Current state (v1.7.1)

Explicit user instruction: "Build step 9" — roadmap Stage II step 9,
C1/C2 seam wiring (docs/MASTERCHECKLIST-2026-07-22.md, Part C). Full
detail: CHANGELOG.md's [1.7.1] entry.

C1 (perception channel): already bounded + pillar-tagged for all five
pillars since B2; "salience-ranked" wasn't — `_pillar_observe_turn`
now sorts candidate Emergence API observations by `magnitude`
(descending) before filling the bounded `working_memory`, instead of
plain recency order, so a pillar's small attention budget goes to
what's actually most salient this turn.

C2 (intention channel): audited every Body-touching write across all
five pillars' representative jobs. Innovation/Nature already validate
(`ontology.validate_hook`/`is_near_duplicate`); Village/Reflection
have no Body-touching writes. Humans' dialect-drift term coining
(`Settlement.lexicon`) was the one real gap — new `narrative_
direction.validate_coined_term()` rejects an exact duplicate before
the write, closing it.

## Current state (v1.7.0)

Explicit user requests: "the adaptive slowing of the simulation should
also adaptively speed up the simulation when LLM load is low and
system is sitting idle"; "continue the roadmap." Full detail:
CHANGELOG.md's [1.7.0] entry.

`_llm_pressure_interval_multiplier()` is now symmetric: below
`LLM_PRESSURE_SPEEDUP_START_RATIO=0.15` it scales ticks DOWN toward
`LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER=0.4` (up to 2.5x faster) as the
LLM backlog approaches genuinely idle, mirroring the existing >=1.0x
slowdown band on the low side — a flat 1.0x zone remains between 0.15
and 0.75. Faster ticks convert idle LLM capacity into more real calls
per second (staggered-daily eligibility is tick-count-based). Surfaced
as `full_diagnostics()["llm_pressure_interval_multiplier"]`.

Roadmap continuation: B8 "Living memory & consolidation" (Stage II
step 8) shipped for all five pillars — `Pillar.consolidate()` folds
the oldest few raw memory notes into one digest once a threshold is
reached, zero LLM cost, called once per closed cognitive cycle via the
existing shared `_pillar_close_cycle` helper (no per-pillar wiring
needed). `reinforce`/`reinterpret` not attempted (needs per-note
salience tracking, flagged follow-up). B9 (self/world-model per
pillar) retroactively marked shipped in the roadmap doc — it was
already subsumed by the earlier B1-generalization pass.

## Current state (v1.6.0)

Explicit multi-part user request: diagnose why `personal_belief`'s
reasoning calls keep falling back; expose `raw_model_output`/`parsed_
json`/`validation_errors`/`fallback_reason`/`fallback_result` in the
dev console for every LLM fallback; refactor to a single-adapter,
fully model-agnostic LLM layer; re-confirm/tune around Nemotron 3 Nano
4B as default. Full detail: CHANGELOG.md's [1.6.0] entry.

Root cause: `personal_belief` asks for a 14-field JSON contract (by far
the largest `deep_reasoning=True` job in the codebase) but shared the
same flat 1.5x token-budget multiplier every simple 2-4-field reasoning
job gets, and can't use a `json_schema` grammar (deliberate, v1.3.37 —
conflicts with the preceding `<think>` block) — a real reasoning trace
over this much required output can plausibly exhaust the budget before
any JSON is written, silently discarded as a generic `calls_errored`.
New `PERSONAL_BELIEF_NUM_PREDICT_MULT=3.0` gives this one job real
headroom (`_schedule_llm_job`'s new `num_predict_mult` param); its
timeout now scales with whatever multiplier was actually used.

Fallback diagnostics: `CognitionRunner.run` now returns a 4th `diag`
element (`fallback_reason`/`raw_model_output`/`parsed_json`/
`validation_errors`) on every failure path — the raw completion text
was already captured by the client before a JSON-parse failure but was
previously discarded by `_run_gated`'s exception handlers; it's now
read straight off the same local `capture` dict already in scope.
Threaded through `_schedule_llm_job` into `_last_llm_calls[name]`
(reachable via `full_diagnostics()`'s existing raw-JSON dev-console
dump — same precedent as `nature_pillar`/`reflection_notebook`, no new
endpoint).

Single-adapter refactor: new `llm.client.LLMAdapter` ABC (`generate_
json`/`build_from_config`) both `OllamaClient`/`LlamaCppClient` now
inherit; `ADAPTER_REGISTRY` is the one dispatch table `build_llm_client`
reads. Adding a new backend = one class + one registry line; nothing
else in the codebase changes (jobs.py/engine.py/every prompt module
already only ever call `.generate_json(...)` on an opaque adapter).

`Config.llm_model`/`llm_backend` already read `nemotron-3-nano-4b`/
`"llamacpp"` (v1.3.36/v0.72.0) — `LlamaCppClient` IS the Nemotron-tuned
default adapter, confirmed rather than duplicated into a parallel
subclass. New `llm_top_p`/`llm_min_p` (both `None`/unset) wired but not
defaulted — a model-card fetch attempt for recommended sampling values
was blocked (403 on every huggingface.co URL tried in this
environment), so no unverified number was guessed; ready for a future
live-tuning pass per this project's standing discipline.

## Current state (v1.5.3)

Explicit user correction, mid-turn: "you have only built nature pillar
up until now, build all the other pillars. Don't do half-jobs.
Complete each and every checklist item fully." Generalizes B1/B2/B3
(v1.5.0-v1.5.2, proven against Nature only by design) to all five
pillars. New `cognition/pillar.py` factories (`default_village_/
humans_/innovation_/reflection_pillar`) + matching new `World` fields,
each pillar proven against ONE real representative existing job
(Village: `_maybe_schedule_beliefs`; Humans: `_maybe_schedule_
narrative_direction`; Innovation: `_maybe_schedule_ontology_proposal`;
Reflection: `_maybe_schedule_reflection`) — same "one real production
call site, not four new designs" discipline B1 established for Nature.
B2/B3's observe/interpret/backpressure/close logic was extracted from
Nature's original inline code into three shared `SimulationEngine`
helpers (`_pillar_observe_turn`/`_pillar_interpret_backpressured`/
`_pillar_close_cycle`, parameterized by pillar name) and Nature's own
job refactored onto them first (verified no behavior change) before
the four new pillars reused the identical helpers — one real
mechanism, not five copies. `full_diagnostics()` gained all four new
pillars, same dev-console-only depth as the existing `nature_pillar`.
Still NOT attempted (unchanged from the Nature-only passes): real
consolidate/forget/reinforce memory, B4 inbox/outbox delivery, and the
full "refactor ~55 scattered jobs into acts of five pillars" — each
pillar has exactly one representative job wired.

## Current state (v1.5.2)

Explicit user instruction: "Continue with roadmap" — Stage II step 6,
B3 "The Attention Scheduler" (docs/MASTERCHECKLIST-2026-07-22.md).
New `cognition/attention.py`: `pillar_salience()` (max `magnitude`
among A22 entries tagged for a pillar since its last turn),
`compute_priority()` (weighted salience/staleness/messages/player-
focus, 0.5/0.3/0.15/0.05), `backpressure_fraction()` (priority ->
0.5..1.0 fraction of the shared backpressure limit, never a full
bypass). `Pillar.last_turn_tick` (persisted) feeds staleness.
`_maybe_schedule_nature_mind`'s `interpret` branch now defers under
backpressure using this priority-scaled fraction instead of the flat
gate every other settlement job shares — quiet/fresh turns defer
earlier, salient/overdue ones tolerate more backlog. Round-robin over
five pillars is trivial with only Nature existing; `message_count`/
`player_focus` both read 0 today (no second pillar or player-focus
mechanism exists yet) but are real, ready inputs. Verified: direct
smoke tests for the priority math's bounds/behavior, an engine-level
test of the real observe-turn wiring and baseline priority computation,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## Current state (v1.5.1)

Explicit user instruction: "Continue with roadmap" — Stage II step 5,
B2 "The continuous cognitive cycle" (docs/MASTERCHECKLIST-2026-07-22.
md), following step 4's Pillar abstraction. `cognition/pillar.py`'s
`Pillar` gained `cycle_stage`/`CYCLE_STAGES`, bounded `working_memory`
(distinct from consolidated `memory`), `note_observation()`/`clear_
working_memory()`/`set_cycle_stage()`. `_maybe_schedule_nature_mind`
now genuinely alternates: an `observe` season reads `World.emergence_
log_recent()` filtered to `"nature"`-tagged entries into `working_
memory` (zero LLM cost — closes C1's perception channel, Nature's
first real read of the Emergence API), advances to `interpret`; the
next season fires the existing LLM call (now also grounded in what was
observed, via a new optional `emergence_observations` param on `llm/
nature_mind.py`'s `build_prompt`), completes remember/plan/act/reflect
synchronously, then returns to `observe`. Real trade: `nature_mind`'s
LLM call volume is now halved (one real call every other season). A
deferred critical call leaves `cycle_stage` on `interpret` — nothing
lost, matches the standing deferral discipline. Verified: direct smoke
tests for `Pillar`'s cycle/working-memory semantics and the prompt
param, an engine-level test of the real `_maybe_schedule_nature_mind`
observe→interpret transition, `scripts/verify_native_soak.py` (2 seeds
x 800 ticks) byte-identical.

## Current state (v1.5.0)

Explicit user instruction: "Start stage 2" — roadmap Stage II step 4
(docs/MASTERCHECKLIST-2026-07-22.md), B1 "The Pillar abstraction," the
doc's own "keystone." New `hearthmind/cognition/pillar.py`'s `Pillar`
class (self_model, world_model — typed revisable theories tagging
observation-vs-hypothesis, memory — capped consolidated-knowledge
list, objectives, inbox/outbox — B4's typed `MESSAGE_KINDS`,
structurally present but unused until a second pillar exists). New
`World.nature_pillar`, seeded via `default_nature_pillar()`.
`_maybe_schedule_nature_mind`'s existing apply() (mechanics unchanged)
now mirrors every belief form/revision into `nature_pillar.
world_model` + a `remember()` note, alongside the untouched `World.
nature_beliefs` every existing reader still uses — additive proof the
shape holds against a genuine production call site. Deliberately NOT
the doc's larger "refactor ~55 scattered jobs into acts of five
pillars" — that's B2 (the continuous cognitive cycle) and the rest of
Stage II. Dev-console-only surfacing (`full_diagnostics()
["nature_pillar"]`). Verified: direct smoke tests for `Pillar`'s
upsert/revise/memory-cap/round-trip semantics plus an engine-level test
of the actual nature_mind mirroring path; `scripts/verify_native_soak.
py` (2 seeds x 800 ticks) byte-identical (the mirrored write only runs
inside a critical LLM job's apply(), never fires LLM-disabled, so this
is a pure regression check).

## Current state (v1.4.9)

Explicit user instruction: "complete stage 1" — roadmap Stage I steps
2-3 (docs/MASTERCHECKLIST-2026-07-22.md), completing Stage I after
v1.4.8 shipped step 1. New `hearthmind/world/fields.py`'s `FieldGrid`
(3x3, matches `WEATHER_REGION_GRID`) + `World.fields`, stepped every
tick; ships one concrete field (`population_density`) wired into
`_choose_fission_site` (avoids crowded regions when an alternative
exists) as a real consumer proof — the other eleven det_sys.md fields
are future follow-ups. R7 deviation flagged (Python, not C++ — a 3x3
grid is too small to justify a native port yet). New `hearthmind/
world/graph_algorithms.py` (weighted-degree centrality over the
relationship ledger) + `Settlement.social_hub_agent_id` +
`SimulationEngine._detect_social_hub` (season cadence, edge-triggered,
zero LLM cost, emits an A22 observation on change). UI: "Social hub"
main-UI stat-tile row (a structural fact about a named person, not
under Phase G's discipline). Community detection was already shipped
as FACTION detection (v0.80.0) under another name — not duplicated.
This closes roadmap Stage I entirely. Verified: direct smoke tests for
both new modules plus the engine detector's edge-triggering/round-trip,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks + a longer single-
seed run crossing a real season boundary) byte-identical.

## Current state (v1.4.8)

Explicit user instruction: "Start step 1: the Emergence API" — the
first implementation step off v1.4.7's roadmap (docs/MASTERCHECKLIST-
2026-07-22.md, A22). New `hearthmind/world/emergence.py` (`Observation`
shape, `OBSERVATION_KINDS`/`PILLARS` closed vocabularies,
`make_observation()`), `World.emergence_log`/`next_emergence_id`
(capped 500, `emergence_log_recent()`), and `SimulationEngine.
_append_emergence` — populated by mirroring `_append_highlight` (via
`_HIGHLIGHT_EMERGENCE_MAP`, all 8 existing highlight kinds), the
reflection hypothesis lifecycle, ontology concept promotion to
`established`, and a new edge-triggered settlement materials-bottleneck
detector (`_detect_settlement_bottlenecks`, riding the existing daily-
metrics cadence). `GET /emergence` + on-demand broadcaster provider,
same shape as `/knowledge-tree`/`/causal-threads`. UI surfacing: dev
console's raw diagnostics dump only (`emergence_log_total`/`_by_kind`/
`_recent`) — same treatment `reflection_notebook` has always had, no
dedicated panel, since nothing consumes this stream yet. Stage II of
the roadmap (the five-pillar refactor) is what will actually read it.
Verified: direct smoke tests (validation, mirroring, cap, round-trip,
bottleneck edge-triggering), `scripts/verify_native_soak.py` (2 seeds
x 800 ticks) byte-identical.

## Current state (v1.4.7)

Explicit user request: file an uploaded consolidated audit ("Hearthmind
— The Complete Master Checklist," Body/Mind/Seam against v1.4.1) into
docs and produce a concrete implementation roadmap. Docs-only. Filed
verbatim as docs/MASTERCHECKLIST-2026-07-22.md with a new appended
"Implementation roadmap" section breaking the doc's own 4-phase
thematic sequence into 30 concrete, independently-shippable steps
(Stage I senses/substrate 3 steps, Stage II the five minds 6 steps,
Stage III player-facing/interaction 5 steps, Stage IV deepen the Body
16 steps; 5 items are standing review-time discipline, not separate
steps). See the "Long-term design vision" section below for the
CLAUDE.md pointer entry and full CHANGELOG.md's [1.4.7] entry for
detail. Planning/filing only — work from it only on future explicit
direction naming a specific step, same standing rule as every other
vision doc here.

## Current state (v1.4.6)

Explicit user follow-up on v1.4.5 with a fresh diagnostic + dialogue
log: self-naming confirmed fixed, but exact-line repeats were still
visible. Root cause: v1.4.5's Jaccard dedup backstop only checks
against `Population.voice_conversation`'s stored ring, capped at
`MAX_VOICE_CONVERSATION_STORED` — the reported repeats recurred ~650
ticks apart (100+ exchanges at the fastest cooldown), well outside the
old 24-entry cap, so the earlier occurrence was long evicted before
the repeat happened. Raised to 220 — cheap (small dicts, still just
the backstop's lookback; the prompt itself still only reads the newest
`VOICE_CONVERSATION_HISTORY_TURNS`).

## Current state (v1.4.5)

Explicit user follow-up after v1.4.4 made voice-pair dialogue visible
for the first time: the actual conversation showed a real repetition
attractor (the same lines — "Ash still smells like home, Osric.",
"Cold bread? I'm already cold from the wind." — recited near-verbatim
many exchanges apart) and speakers sometimes naming THEMSELF
mid-line instead of only ever naming the other person. Fixed with the
established "prompt hint + deterministic backstop" pattern (same shape
as folklore's v1.3.2 dedup fix): `VOICE_SYSTEM_PROMPT` now asks the
model not to repeat an image/complaint and never to say its own name;
new `dialogue._is_near_duplicate_line`/`VOICE_LINE_DUPLICATE_
OVERLAP=0.6` (Jaccard word overlap against a speaker's OWN full stored
`voice_conversation` history, not just the ~6-turn prompt window) and
`dialogue._strip_self_address` are the deterministic backstops,
wired into `parse_voice_dialogue`/`SimulationEngine._run_voice_
dialogue`. A repeated line degrades only its own side to the
fallback pool, not the whole exchange.

## Current state (v1.4.4)

Explicit user follow-up on v1.4.3 with a fresh review pack +
`/diagnostics` attached: reasoning calls still failing, no voice-pair
dialogue visible in the UI, some completions truncated mid-sentence,
plus a request to expose deep-reasoning-specific diagnostics. Four
distinct bugs fixed — full incident writeup in CHANGELOG.md's [1.4.4]
entry:

1. **Timeout misclassification**: `urlopen`'s socket-level timeout is
   strictly smaller than `jobs.py`'s outer `asyncio.wait_for` — the
   inner one always fired first and raised plain `LLMUnavailable`,
   so `calls_timed_out` was structurally incapable of ever
   incrementing (0 in every diagnostic to date). New `client.
   LLMTimeout(LLMUnavailable)` fixes the classification.
2. **Reasoning calls needed a longer timeout**: `personal_belief`
   showed p95 latency 146.7s against an un-scaled 125s timeout — new
   `DEEP_REASONING_TIMEOUT_MULT=1.5` scales it the same way `DEEP_
   REASONING_NUM_PREDICT_MULT` already scales the token budget; both
   clients gained a `timeout_override` param threaded end to end.
3. **Truncation**: a `json_schema`'s `maxLength` is enforced at the
   character level with no chance for the model to finish its
   sentence — `client._trim_truncated_string(s)` trims a near-cap
   value back to the last complete sentence/clause.
4. **"No dialogue at all"**: a real UI bug, not a backend gap — since
   v1.4.0, `is_llm` in `_apply_pending_dialogue_results` can only ever
   be the voice pair, but an ordinary (non-`surfaced`) line still
   logged under the `skip: true` `dialogue` category, a holdover from
   when many core-cast pairs produced real LLM chatter. Fixed: a new
   visible `voice_dialogue` category (💬); `dialogue_surfaced` (💬✨)
   stays for the stronger case.

Also: `CognitionRunner` gained `reasoning_calls_*` counters + a
reasoning-only latency window (new `reasoning` sub-object in `llm_
stats`), and `reasoning: bool` is now tagged on `_last_llm_calls`/
`llm_prompt_stats` entries — per explicit request, so a future
reasoning-specific failure is traceable per-task.

## Current state (v1.4.3)

Explicit user follow-up on v1.4.2: calls were still erroring (100% on
`mind`, a task that was never `deep_reasoning`) after `LLAMA_REASONING
=auto` (v1.3.37). Root cause: the per-call "detailed thinking off"
system-prompt phrase is only a soft hint this model doesn't reliably
honor — it kept reasoning anyway, running the completion past `max_
tokens` mid-`<think>` with no JSON ever emitted, and `_THINK_BLOCK_RE`
only matched a *closed* pair so the truncated trace reached `json.
loads` whole and failed. Fixed at the request level, not the prompt
level: both LLM clients now send a genuine per-request reasoning
override (`llama-server`'s `reasoning_budget: 0` + `chat_template_
kwargs.enable_thinking: false`, sampler-enforced) whenever `reasoning=
False` — see `llm/client.py`'s `_REASONING_OFF_PROMPT` docstring for
the full incident writeup. New `_UNCLOSED_THINK_RE` strips a dangling
never-closed `<think>` block as defense-in-depth. Also, explicit user
directive: reasoning is now load-shed, not just crucial-task-gated —
`REASONING_LOAD_SHED_RATIO=0.9` in `simulation/engine.py` drops a
`deep_reasoning=True` job to its fast reasoning-free path once `llm_
pressure_ratio()` crosses it, before pacing/pause even engage. See
CHANGELOG.md's [1.4.3] entry for full verification detail.

## Current state (v1.4.2)

Live-diagnostic fix: a pasted `/diagnostics` showed `voice_dialogue`
(now the highest-volume LLM task after v1.4.1's cooldown drop) erroring
50% of the time — it was the one dialogue-shaped call site never given
a `json_schema` (didn't exist when FT.0's schema set was built), so it
free-generated unconstrained on a model that visibly doesn't reliably
keep meta-commentary out of its answer (a same-snapshot "mind" call
succeeded but its `voice` field contained leaked reasoning text). New
`"voice_dialogue"` entry in `llm/json_schemas.py`, wired into
`_run_voice_dialogue`. Also hardened both LLM clients' final JSON parse
with a new `_extract_json_object()` fallback (first-`{`-to-last-`}`
substring retry) for every remaining unconstrained task (`beliefs`/
`personal_belief`) — recovers a completion wrapped in stray prose or a
markdown fence. The garbled-but-schema-valid "mind" content itself is a
separate model-quality issue, not fixed here (a schema only guarantees
shape, not semantic quality).

## Current state (v1.4.1)

Explicit user follow-up on v1.4.0's voice pair: much more frequent
triggering (`VOICE_DIALOGUE_COOLDOWN_TICKS` 60 -> 5) and a "shifting
protagonists rather than permanent stars" directive — the pair should
rotate roughly weekly, selected by narrative significance (mayor one
week, a grieving parent the next, later an inventor/rebel/council
elder) rather than fixed prominence. New `Population._narrative_
significance` layers grief/emotion/feud("rebel")/extreme-event-count
bonuses on top of the existing `_prominence` baseline; `select_voice_
pair` now picks a "protagonist" this way then partners them with their
strongest core-cast bond. `maintain_voice_pair(week_rotation=...)` is
called with `"week_end" in events` each tick — a real calendar
boundary, not a synthetic timer — forcing reselection without a forced
"never repeat" rule (same winner two weeks running is a no-op, not a
change). Two signals needing `World`/`Settlement` (recent inventor,
active COUNCIL membership) are computed in `SimulationEngine._voice_
narrative_extra_scores()` and passed in, since `Population` stays
decoupled from those layers.

## Current state (v1.4.0)

Explicit user directive: LLM dialogue disabled for every NPC pair
except one fixed core-cast pair (`Population.voice_pair_ids`), freeing
the budget that used to spread across several core-core pairs into one
genuinely deep, continuing conversation — longer lines (`VOICE_MAX_
LINE_WORDS=40` vs 26), real turn-to-turn continuity via a persisted
`voice_conversation` thread fed back into each prompt, grounded in a
concise town digest + each speaker's own internal state, called far
more often (`VOICE_DIALOGUE_COOLDOWN_TICKS=60` vs the ordinary 300).
Rotates to the survivor's strongest remaining bond on death (or a
fresh pair if both die), logged as a `voice_pair_change` event. Every
other pair — including former core-core ones — is now deterministic-
only; `due_for_dialogue` no longer partitions core vs. crowd at all.
New `llm/dialogue.py` voice-mode prompt/parse path
(`build_voice_prompt`/`parse_voice_dialogue`), deliberately separate
from ordinary `build_prompt` (tuned for brief small talk between
near-strangers) rather than a mode flag — its parsed output still
carries the Phase-2 structured-outcome fields at inert defaults so it
reuses the same `_apply_pending_dialogue_results` pipeline (is_llm-
gated event surfacing already meant only genuine LLM exchanges reach
`/events`, now sharper since there's exactly one such pair).

## Current state (v1.3.41)

Explicit user follow-up ("Yes do that") shipping the four Living
Terrarium items deferred from v1.3.40 as UI-heavy: 1.5 (a "⚖ laws of
nature" panel — filtered/reformatted `/knowledge-tree` data, a
validated/untested badge from `TriggerRule.fire_count`), 3.3 (legible
causal threads, scoped to dispute outcomes — the grounding facts
already computed for the LLM prompt are now captured as a `world.
ontology.CausalThread`, surfaced via a new "🔗 causal threads" panel),
3.5 (a "🌳 N things known so far" line on the timeline scrubber,
reconstructed for any past tick by counting current knowledge-tree
entries with origination tick `<= X` — no new history needed), and 3.6
(a faint seasonal color-grade over the map, `#season-vignette`,
darkening toward winter; ambient audio's existing weather/night/
temperament inputs gained Nature's Mind belief confidence). All four
items were already partly shipped under other names (replay/export,
ambient audio, era cartography) — each pass's own scoping note in
docs/VISION-2026-07-22-LIVINGTERRARIUM.md details the real delta.

## Current state (v1.3.40)

Explicit user directive: "Start all of that" — the remaining Living
Terrarium vision-doc items plus four flagged v1.3.38 audit follow-ups.
Scoped down to the backend/data-model-tractable half; 1.5/3.3/3.5/3.6
(all real UI-heavy efforts) deliberately deferred as their own future
batch rather than rushed shallowly — see docs/VISION-2026-07-22-
LIVINGTERRARIUM.md for each item's own scoping note. Full detail:
CHANGELOG.md.

Shipped: 1.1 composable hooks (`TriggerRule` secondary trigger/hook
pair, own cooldown), 4.2 species variants (`world.wildlife.
SpeciesVariant`, identity-only — deliberately NOT wired into
`AnimalHerd`'s native-parity-critical fields), 5.3 coherence/drift
detection (an ontology-abandonment Reflection hypothesis, consumable
by self-tuning as a new `ontology_proposal_chance` governor), 5.4
provenance (`knowledge_tree()`'s new `"who"` field on every entry
type, surfaced in the existing knowledge-tree panel) — plus all four
audit items: reflection `kind="question"`/`"conclusion"` entries
(zero added LLM volume — reuses the existing year-cadence slot and a
deterministic status-transition hook), a real plan-fulfillment memory
on `Agent.plan` expiry, relationship-weighted SOCIALIZE targeting,
and genesis-time `Agent.long_term_goal` seeding via `llm/mind.py`
(fallback-less — a blank answer just means the existing monthly job
still forms one later).

## Current state (v1.3.39)

Explicit user request: implement Living Terrarium items 4.1 (composite
entities from existing primitives) and 4.3 (generative assets bound to
emergent entities).

New `world.ontology.CompositeEntity`: structurally just composition —
one real standing building (unchanged kind/mechanics) bound to one real
`InventedConcept` via a name + origin story grounded in an actual
recent event, the doc's own "Sorrow-Hall" shape. `llm/composite_
entity.py` (closed category/hook vocabulary, `validate_hook` reused)
+ `SimulationEngine._maybe_schedule_composite_entity` (seasonal,
round-robin settlement, real fallback name) name the oldest unnamed
standing building in a settlement. New `world/sigils.py`'s `generate_
sigil_svg(name, category)`: fully deterministic parameterized SVG (hash
-> palette/motif/rotation, zero LLM cost), generated once at entity
creation and stored on `CompositeEntity.sigil_svg`. Surfaced main-UI:
the building click inspector shows a named building's sigil/name/
origin story.

## Current state (v1.3.38)

Explicit user request: a cognition-architecture audit (not prompt
wording) covering five angles — text-only calls that could write
persistent state, deterministic judgment calls that could become real
LLM cognition, decision-horizon opportunities (plans/goals/hypotheses)
over more narration, fewer-but-persistent-and-conditioning calls
instead of isolated generations, and agents/settlement forming
hypotheses/carrying intentions across months-years — plus finishing a
few docs/VISION-2026-07-22-LIVINGTERRARIUM.md items.

Audit findings (full detail: CHANGELOG.md): `World.reflection_
notebook` is the only real "test my own belief against evidence" loop
in the codebase; several settlement-scoped LLM outputs (culture_
digest/institution_culture/narrative_direction, chronicler Q&A) are
write-once islands nothing downstream reads; `Agent.plan` silently
expires with no fulfilled/abandoned judgment; SOCIALIZE targeting and
`_maybe_assign_occupations` are judgment calls dressed as heuristics.
Flagged, not shipped: reflection `kind="question"`/`"conclusion"`
entries, a plan-fulfillment check, relationship-weighted SOCIALIZE,
seeding `Agent.long_term_goal` at genesis.

Shipped items 2.2 and 3.4 from the vision doc. 2.2: `Institution.
objective_ticks_unmet` tracks how long an institution has wanted the
same unmet thing (incremented in the existing monthly `institution_
belief` job, zero added LLM volume); `_maybe_schedule_rule_proposal`
grounds its prompt in whichever institution is stuck longest past
`INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD` — real institutional
will reaching into the Innovation Layer's rule pipeline. 3.4: new
`llm/musing.py` + `World.musings` (capped, daily texture) +
`_maybe_schedule_musing` (day_end, ambient, real fallback) — grounded
in the newest open Reflection hypothesis or newest knowledge-tree
entry, skipped entirely with nothing to muse on. Surfaced main-UI (a
"💭" header line off the live broadcast's `latest_musing`) since this
is explicitly meant to be seen, unlike Phase G's dev-console-only
discipline.

## Current state (v1.3.37)

Explicit user directive, table-form: enable real reasoning traces
(Nemotron 3's "detailed thinking on") for personal belief revision,
major life decisions, council deliberation, town consciousness,
cultural evolution, and innovation & discovery — keep it off for
dialogue/rumors/dreams/moment-to-moment cognition; change `scripts/
run.sh` defaults if required; reallocate the freed budget toward
tasks that need genuine sentience/intelligence, not narration.

Found the real blocker first: `scripts/run.sh`'s `LLAMA_REASONING`
defaulted to `off` (server-wide `--reasoning-budget 0`), which made
every `deep_reasoning=True` job's per-call "detailed thinking on"
phrase a no-op no matter what the app sent — default now `auto`.
`_schedule_llm_job(..., deep_reasoning=True)` now flags ~20 tasks (was
2: Innovation Layer propose/evolve only) — belief revision (personal +
settlement), major life decisions (migration/fission/founding/
dispute), institutional/council deliberation, town consciousness,
cultural evolution (tradition/religion/narrative direction/culture
digest/institution culture/faction/laws/rule proposals), invention,
and the Reflection/self-tuning system that lets the game learn and
improve itself. `personal_belief`/`beliefs` lost their `json_schemas.py`
grammar entries — a schema-constrained call structurally can't also
carry a reasoning trace, and belief revision benefits more from the
trace. `DIALOGUE_BACKPRESSURE_FRACTION`/`RUMOR_INTERPRET_BACKPRESSURE_
FRACTION` lowered (0.75->0.6, 0.5->0.35) so pure narration sheds its
queue slot earlier, freeing the shared concurrency limit for the now
much larger set of genuinely-reasoning tasks.

## Current state (v1.3.36)

Explicit user directive, two parts: (1) "move the LLM from describing
the world to thinking within the world," clarified via follow-up as
an audit-driven expansion of genuine decision points — classify every
decision as deterministic (keep in code) / subjective cognition (move
to LLM) / hybrid (code finds facts, LLM chooses/interprets) — NOT a
prompt-wording/person-framing change; (2) "optimize all the prompts
and parser to work with Nemotron 3 Nano 4B." This is the opposite
direction from v1.3.35, which stays correct (that pass's five
conversions were genuinely objective once separated from narration;
this pass's is a genuine judgment call) — both are right, applied to
different decisions.

Ships the audit's #1-ranked item: individual migration decisions.
New `llm/migration.py` (same candidacy/decision split as `llm/
fission.py`) — `Population.migration_push_target`/`core_migration_
candidates`/`depart_for_migration` extract the deterministic
preconditions and effects (unchanged logic), a new `_maybe_schedule_
migration_decision` engine job asks the LLM to actually weigh a
core-cast agent's life against a real push/pull reason to leave;
declining is a real outcome. Core-cast-gated per the standing rule;
non-core agents keep the original flat-chance-roll path unchanged.

Nemotron 3 Nano 4B is genuinely hybrid-thinking (unlike the prior
Gemma default) but toggles its `<think>` reasoning purely via an exact
system-prompt phrase ("detailed thinking on"/"detailed thinking off"),
not an API field — both LLM clients' `generate_json` gained a
`reasoning` param implementing this (plus Ollama's native `"think"`
field for Qwen3), reusing the existing `deep_reasoning` flag (Phase
3.A) rather than adding a new one; structurally never combined with
`json_schema` (`reasoning = deep_reasoning and task_schema is None`
in `_schedule_llm_job`) since a grammar suppresses a preceding
`<think>` block. `Config.llm_model` default -> `nemotron-3-nano-4b`.

Audit's remaining items — `choose_building_kind`, SOCIALIZE targeting
(highest call volume, likely needs a heuristic fix first), `_maybe_
assign_occupations` — flagged as follow-up.

## Current state (v1.3.34)

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md's own sequence:
item 5 ("1.4 + 2.4 — the world tuning and modifying itself, inside
guardrails"). New `World.wildfire_ignition_ticks` feeds a governor-
drift branch in `_detect_reflection_pattern` (realized vs. theoretical
gap between ignitions, `disasters.WILDFIRE_CHANCE_PER_WEEK`) — once
that becomes a `supported` Reflection hypothesis, `llm/self_tuning.py`
proposes a bounded direction+magnitude nudge to `World.governor_
tuning["wildfire_chance"]` (band `disasters.GOVERNOR_TUNING_BAND=0.3`
enforced by the interpreter, never trusted from the model). `_maybe_
schedule_self_tuning` (critical=True, year-cadence) never touches real
state until `simulation.sandbox.run_counterfactual` validates the
tuning on a disposable deep-copied world first — item 1.3's sandbox
actually gating a real self-modification. Every attempt logs to new
`World.self_tuning_actions` (append-only, never pruned); an applied one
also appears in `knowledge_tree()`. Dev-console surfacing only, same
treatment as `reflection_notebook`.

## Current state (v1.3.33)

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md's own sequence:
item 4 ("2.1 + 2.3 — Nature that adapts and can surprise the
humans"). 2.1: `terrain_evolution.nature_adaptation_bias()` reads the
confidence of Nature's Mind's strongest belief about repeated fire/
flood damage; `decay_disaster_scars` now speeds scar recovery up to
`NATURE_ADAPTATION_DECAY_BONUS_MAX=0.5` faster when that belief is
confident — bounded, directed adaptation, not a raw random walk.
Scoped to disaster scars specifically since they're confirmed to have
no native C++ counterpart, so this adds zero native/fallback parity
risk. 2.3 (scoped): a genuinely NEW Nature's-Mind belief bumps
`pattern_signal_counts["nature_adaptation"]`, the same pressure-signal
dict `_maybe_schedule_ontology_proposal`'s gate already reads — a
poor/small settlement can now become eligible for a Village ontology
proposal purely from Nature's own unprompted insight. Ships the
Nature -> Village half only; the reverse direction is flagged as the
sequel once 2.2 lands.

## Current state (v1.3.32)

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md's own sequence:
item 3 ("5.1 + 5.2, ship before turning up self-modification"). 5.1:
`world.ontology.retire_stale_rules` — an active `TriggerRule` that's
never once fired (`fire_count == 0`) past `TRIGGER_RULE_STALE_
TICKS=40_000` is retired, the runtime-acceptance-auditor gap
`InventedConcept` already had (`abandon_stale`) but the newer
`TriggerRule` didn't. 5.2: `simulation/sandbox.py`'s `run_
counterfactual` gained an unconditional population-extinction floor
and a resource-explosion ceiling (total settlement materials >5x
start); "no governor can be disabled" holds structurally since
`TriggerRule.hook_type` is drawn from a closed vocabulary that never
touches `Config`.

## Current state (v1.3.31)

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md down its own
stated sequence ("1. 3.1 + 3.2 ... 2. 1.2 + 1.3"): item 3.1 (the
away-digest's "front page" — `World.away_digest_highlights`, every
`knowledge_tree()` entry originated since the digest's own window,
zero extra LLM cost); item 1.2 (`world.ontology.TriggerRule` +
`TRIGGER_TYPES` — a village-originated rule binding a real trigger
on_death/on_birth/on_feud/on_invention/on_drought/on_surplus to a real
`MECHANICAL_HOOK_TYPES` effect, wired to each trigger's actual
pre-existing detection point in the engine, cooldown-gated against
runaway repeated firing); item 1.3 (`simulation/sandbox.py`'s
`run_counterfactual` — before a proposed rule goes live, deep-copies
the world, runs the fork 50 ticks LLM-disabled, and checks it doesn't
crash or explode the population; an unsafe proposal is discarded and
logged, never silently dropped). Only `belief_confidence_bonus` is
actually consumed as a numeric effect this pass — other hook types
stay narrative-only, flagged (matching `InventedConcept`'s own
pre-existing not-yet-consumed hooks, not newly introduced debt).

## Current state (v1.3.30)

New user-uploaded vision doc, docs/VISION-2026-07-22-LIVINGTERRARIUM.md
("The Living Terrarium: Completing the Vision") — the next-frontier
follow-up to docs/VISION-2026-07-21-SELFEVOLVING.md, mapping five
capabilities: (1) self-modifying mechanics via data-not-code
(composable hooks, a trigger→effect rule vocabulary, Reflection's
counterfactual sandbox as the safety gate, bounded self-tuning), (2)
Nature/institutions acting on their Minds not just narrating them, (3)
the daily-peek experience (morning-paper digest, knowledge tree,
causal threads, the world musing to the observer, time-lapse, ambient
presence), (4) new entities/assets via composition (+ optional
generative representations), (5) runtime safety guardrails (acceptance
auditor, invariant floors/ceilings, coherence/drift detection,
provenance). Ships its own priority sequence; work from it on future
explicit direction naming a specific item, same convention as the
other vision docs.

This pass ships item 3.2 only ("What the world learned" ledger,
[CERTAIN], first in the doc's own sequence): `World.knowledge_tree()`
aggregates every LLM-originated persistent entity across all four
pillars + Reflection (invented concepts w/ lineage, settlement laws/
customs/taboos, Reflection hypotheses, Nature's beliefs) into one
newest-first, read-only, already-capped list — zero new state, zero
new LLM call. New `GET /knowledge-tree` (via a `WorldBroadcaster`
on-demand provider hook mirroring `full_diagnostics`'s) + a "🌳
knowledge tree" explore-menu panel, same pattern as the existing
highlights panel.

## Current state (v1.3.29)

Explicit user directive: audit every LLM call site, classify each by
role (dialogue/planning/narration/cognition/other), and refactor only
where necessary so every LLM interaction passes through a single
cognition interface, without changing gameplay. Finding: the
unification mostly already existed — `_schedule_llm_job` is already
the shared interface ~30 settlement/world-scoped jobs go through
(budget consume, backpressure convention, JSON-schema decoding,
critical-vs-ambient fallback discipline, debug/call recording).
`_run_cognition`/`_run_dialogue` stay as documented, structurally-
necessary exceptions (pending-result queues + staleness handling).
`_maybe_interpret_rumor` was the one undocumented bypass — migrated
onto `_schedule_llm_job`, removing its duplicated bookkeeping; one
deliberate behavior change flagged (budget-exhausted days now apply
the deterministic fallback retelling instead of silently skipping,
matching every other ambient job's convention). `server.py`'s one-shot
world-genesis call and `llm/rejection_sampling.py`'s standalone offline
tool are legitimate, out-of-scope exceptions, left as-is.

Also removed three leftover `.claude/worktrees/agent-*` git worktrees
(and their branches) from prior background-agent sessions — verified
clean (no uncommitted changes) and fully merged (ancestors of this
branch) before removal.

## Current state (v1.3.28)

Explicit user directive: "Start the 5th item and extend LLM 4-5
pillars." Reflection (Phase 5) is the meta-cognitive system observing
the four Minds (Humans, Village, Nature, Innovation) — not a fifth
pillar, per v1.3.27's Body/Mind correction. Ships 5.A + 5.B only;
5.C (counterfactual sandbox)/5.D/5.E (self-improvement recommendations)
stay design-only.

New `World.reflection_notebook`/`next_reflection_entry_id`: typed,
never-pruned `ReflectionEntry` records (observation/hypothesis/
experiment/conclusion/question, confidence, evidence_for/against,
open/supported/rejected/superseded status) — a rejected hypothesis
stays as historical knowledge, never deleted. New `llm/reflection.py`
+ `SimulationEngine._maybe_schedule_reflection` (world-scoped,
`season_end`, `critical=False` — ambient self-improvement, keeps a
real deterministic fallback). Each firing: deterministic pattern-
detection reusing existing counters across all four pillars with zero
new instrumentation beyond one read-only aggregate (`pattern_signal_
counts` for Village/Human, `WildlifeGrid.summary()`'s `prey_scarce`/
`predator_pressure_ratio` for Nature, established-concept category-
imbalance over `world.invented_concepts` for Innovation) -> one LLM
call proposes a grounded hypothesis (skipped if an open hypothesis
already shares the pattern's subject) -> every existing open
hypothesis gets a small bounded confidence nudge from fresh evidence,
no LLM call, transitioning to supported/rejected at threshold. Surfaced
via `_diagnostics_snapshot()` only (dev-console/raw-JSON depth,
Observatory UI split).

## Current state (v1.3.27)

Explicit user correction ("The self-evolving ontology is not the
responsibility of the Innovation pillar alone... every pillar
continuously expands the ontology") plus "scope Nature's Mind next and
start building whatever you can." Two docs corrections plus one real
implementation slice, see "Design priorities" above for the standing
rules recorded from this pass.

New `llm/nature_mind.py` + `SimulationEngine._maybe_schedule_nature_
mind`: world-scoped, `season_end`, `critical=True` (deferred not
faked). Grounded only in Nature's Body state (wildlife trophic ratios,
disaster/mining scar counts, fallow/succession progress, climate
drift, season) — one LLM call forms/revises a `World.nature_beliefs`
entry (same shape as `Settlement.beliefs`) and may originate one
`category="ecological"` concept into the shared ontology registry.
`llm/ontology.py`'s new `VILLAGE_PROPOSE_CATEGORIES` excludes
`ecological` from the Village-imagination job — that category is now
Nature's exclusive territory, closing the accidental "all ontology
categories gated on settlement prosperity" collapse. Surfaced: `World.
summary()`'s `nature_beliefs`, a "The land's own sense" stat tile.

## Current state (v1.3.26)

Explicit user follow-up: "continue with food webs and predator-prey
feedback" — the last open Phase 3.D item.

The existing hunt/starve mechanic already had a real per-tile loop
(predator reproduction was gated on a successful same-tile hunt;
starvation fired without one) — the actual gap was that it was purely
local, blind to map-wide population trends. `world/wildlife.py`'s
`WildlifeGrid.tick()` now computes `predator_pressure_ratio` (total
predator animals / total grazer animals) and `prey_scarce` (grazer-herd
count vs. world-gen's own `GRAZER_TO_PREDATOR_RATIO` expectation) once
per tick — cheap O(n) aggregates, R7-deviation-flagged Python, same
precedent as the scar/soil modules. Heavy predator pressure now halves
grazer reproduction map-wide (a "landscape of fear" effect beyond
direct kills); prey scarcity halves predator reproduction and doubles
starvation risk even for a pack with a lucky hunt that tick. Surfaced
in `WildlifeGrid.summary()` and the Wildlife stat tile.

## Current state (v1.3.25)

Explicit user follow-up: "continue with 3.C and 3.D" — the two
remaining open Phase 3 items in docs/VISION-2026-07-21-SELFEVOLVING.md.

3.C: `world/ontology.py`'s new `dominant_architecture_concept(world,
settlement_id)` (categories `technology`/`institution_flavor` only —
the two that plausibly reshape what gets built) feeds a per-settlement
`architecture_styles` map into the broadcast payload;
`SimulationEngine._maybe_broadcast` tags each building with its
`settlement_id` at broadcast time (not persisted). `app.js` outlines a
settlement's buildings in a color hashed from the concept id and names
the style in the building hover tooltip. 3.D: `maybe_reclaim`'s
instant grassland->forest flip now requires `REFOREST_MIN_FALLOW_
WEEKS=3` consecutive qualifying weeks first, tracked in new `World.
fallow_ticks` (same additive-dict-overlay shape as `mining_scars`/
`disaster_scars`). Caught a real bug while verifying: the Python
fallback path iterated its eligible-tile set in undefined hash order,
drawing RNG differently than the native path's row-major scan —
`scripts/verify_native_soak.py` caught the resulting divergence at
tick 1727; fixed by sorting the fallback's iteration into the same
`(y, x)` order.

Food webs/predator-prey feedback, river course drift, and
ecology->weather feedback remain explicitly flagged, not attempted.

## Current state (v1.3.19)

Explicit user follow-up on Phase 1: invented concepts must be real
building blocks — "any system can discover, reference, reinterpret,
combine, mutate, and build upon indefinitely," not inert flavor.
Elevates combine (merge)/mutate (evolve) into this same pass rather
than deferring them. New `world/ontology.py` (`InventedConcept` +
`World.invented_concepts` registry, world-scoped) and `llm/ontology.py`
(propose/evolve/merge pipelines, deterministic `validate_hook` re-
verification, never an LLM self-check). Bounded, not fully open:
category/hook-type are closed vocabularies (enums partly mirrored into
the C++ native store make runtime schema mutation unsafe); name/
description/lineage are genuinely open-ended. Lineage (`evolved_from`/
`merged_from`) is a real DAG — evolving/merging never destroys a
parent concept, so reinterpretation chains stay walkable.
`_maybe_schedule_invention` (existing, unchanged mechanically) now
also registers a `technology`-category concept — the bridge that
keeps this from duplicating a disconnected registry; new `_maybe_
schedule_ontology_proposal` covers the other seven categories, new
`_maybe_schedule_ontology_evolution` does evolve/merge (rare, world-
scoped), new zero-LLM-cost `_maybe_spread_concepts` grows adoption
(documented simplification — full reuse of `invention_knowledge`'s
teach/lose/rediscover lifecycle is a flagged follow-up). `town_brain.
build_prompt` references established concepts as grounding — proof
any system can read what Innovation produces. Verified: unit tests,
World round-trip, a 6000-tick real-engine run with the new jobs live,
native soak byte-identical. Main-UI stat tile flagged as fast-follow
(dev-console diagnostics counts shipped now); Phases 1.B/1.C/1.D
(Humans' long-term goal, Village NPC->cognition, Nature->Human
disaster scarring) and Phase 2+ remain open — see the vision doc.

## Current state (v1.3.18)

Explicit user directive: "Start Phase 0" of `docs/VISION-2026-07-21-
SELFEVOLVING.md` — the shared pairwise ledger every later self-
evolving-world phase needs. New `agents/ledger.py`: `LedgerEdge`
(fondness/trust/debt/flag/grievances + new `promises`/`history_tags`
for Phase 2/3) and `Ledger`, consolidating what were five separate
`Agent` dicts (`relationships`/`trust`/`debts`/`relationship_flags`/
`grievances`) into one shared per-pair store. Each of the five is now
a dict-like view over the shared ledger (`_FieldView`/`_GrievanceView`)
— same external shape, ~90 existing call sites needed zero edits, same
"compatibility-shim property" discipline `AgentStore` (v0.65.0)
established. Native soak caught a real bug mid-migration: `_record_
debt` writes `giver.debts[id] = 0.0` then immediately re-reads it —
comparing against a "neutral value means absent" default would have
auto-pruned the edge on that write, turning the re-read into a spurious
KeyError. Fixed with a genuine `None` presence sentinel on the three
float fields (explicit 0.0 stays a valid, readable, present value)
and removing all auto-pruning from `__setitem__` — only explicit `del`/
`.pop()` prunes now, matching the plain-dict semantics being replaced.
Verified: direct unit tests, all of v1.3.17's Tier 0/2.2 tests re-run
unmodified against the new backing, `verify_native_soak.py` byte-
identical (2x800 + a 4000-tick single-seed run — the run that actually
caught the bug above). Phases 1-4 of the self-evolving-world roadmap
remain open; see the vision doc.

## Current state (v1.3.17)

Explicit user request: implement items from an uploaded audit,
`docs/archive/DEFINITIVECHECKLIST-2026-07-21.md` — a dependency-ordered,
tiered rewrite plan whose central finding is that interpersonal state
(feuds, debts, grievances) ambiently decays to zero exactly like mood
does, and disputes (the one interpersonal LLM job) are throttled to a
cooldown that measurably never fires — so nothing between two specific
people can ever accumulate into real history. Ships the audit's own
Tier 0 ("stop the self-erasure," the dependency root everything else
needs) + Tier 2.2 (un-throttle disputes) only, this pass — Tier 1 (a
full pairwise-ledger migration replacing the scattered relationship/
trust/debt scalars) is explicitly flagged as too large/risky to
attempt in the same batch without live-testing every migrated call
site; Tiers 2.1/2.3 and 3-7 (interpersonal LLM scene-jobs, wants-
driven goals, consequence loops, dialogue-as-transaction, life arcs,
N1-N3 environmental wiring) are real follow-up work, not silently
dropped — see the checklist doc's own per-item shipped/not-shipped
notes.

`Agent.relationship_flags` (id -> `"feud"`, set by `apply_dispute`'s
feud/ostracism outcomes) exempts that pair from BOTH the ambient decay
AND the passive colocation-warmth gain in `Population.
_update_relationships` — "hardened for good" now actually holds
instead of eroding back toward neutral every tick; only an explicit
reconcile/council_ruling clears it. `Agent.debts` at/above new
`DEBT_SIGNIFICANT_THRESHOLD=2.0` stops passive decay in `decay_debts`
entirely. New `Agent.grievances` (id -> small FIFO-capped tagged-text
list, `MAX_GRIEVANCE_TAGS_PER_SOURCE=3`) is a protected store separate
from the churning 8-slot `memories`/`working_memory` — written at
feud/ostracism/theft time, immune to `MAX_AGENT_MEMORIES` eviction,
cleared only by explicit reconciliation. `DISPUTE_COOLDOWN_TICKS`
3000 -> 1000 (still backpressure-gated, so LLM volume can't blow out);
`due_for_dispute` now fires on EITHER side's relationship crossing
`DISPUTE_RELATIONSHIP_THRESHOLD` rather than requiring mutual souring
— `_maybe_schedule_dispute` reads the worse of the two directions into
the prompt so a one-sided dispute's framing isn't misleadingly mild.
Both new dicts get the same dead-agent cleanup as relationships/trust
(v0.42.0's leak fix). Deliberately did NOT blind-reflag the 36 existing
`_remember(routine=)` call sites (checklist's other Tier 0.2 half) —
that needs live measurement/judgment per site, a wrong call could
suppress genuinely significant memories instead of routine ones.

Verified: direct unit tests (debt-significance skip, decay-lock +
gain-lock on a flagged pair, grievance cap/clear, `to_dict`/`from_dict`
round trip, one-sided dispute trigger + cooldown + `apply_dispute`
outcome wiring), `scripts/verify_native_soak.py` byte-identical (2
seeds x 800 ticks, plus a 4000-tick single-seed run past the
checklist's own 3685-tick reference window).

## Current state (v1.3.24)

Explicit user request: "start both" — Phase 3's last open 3.A item
plus starting Phase 4.

3.A: `world/ontology.py`'s `maybe_promote_status` now scales adoption
thresholds against the origin settlement's core-cast headcount (only
core-cast members can become tracked adopters), floored at the
original flat values.

Phase 4 initial audit: spot-checked cross-pillar wiring (Nature<->
Human, Village<->Human, Nature<->Village) — no gap found. Persistence-
generalization item resolved as "already consistent by design": the
Tier 0.1 decay-lock exists because interpersonal rupture should never
silently heal, the opposite intent from disasters/landscape-scars
(deliberately DO heal if left alone) — applying a lock there would
contradict the mechanic. Village-identity fields checked clean (no
decay mechanic at all). See docs/VISION-2026-07-21-SELFEVOLVING.md's
Phase 4 section for the full writeup.

Verified: direct smoke tests, `scripts/verify_native_soak.py` (2 seeds
x 3000 ticks) byte-identical.

## Current state (v1.3.23)

Explicit user follow-up ("continue"): closes 3.B's two remaining
unshipped items. `OCCUPATION_STATUS_BONUS` (mayor/priest) feeds
`Population._prominence` directly — the positive counterpart to
`standing_penalty`'s ostracism-only signal, consumed by council
eligibility/core-cast refill. `OCCUPATION_DIALOGUE_REGISTER` (priest/
banker/mayor/teacher/scribe) is a light manner-of-speaking hint in
`dialogue.build_prompt`. Same-occupation-rivalry deliberately not
attempted — no colocation-detection mechanism exists yet.

Deeper inheritance: `_apply_inheritance` gained a personal-belief
transfer at `INHERITANCE_BELIEF_CHANCE=0.4`, same imperfect-
transmission shape as the existing lesson inheritance, at reduced
confidence.

Verified: direct smoke tests, a 5000-tick LLM-disabled engine run with
round-trip byte-equality, `scripts/verify_native_soak.py` (2 seeds x
3000 ticks) byte-identical.

## Current state (v1.3.22)

Explicit user request: "complete phase 2 and start phase 3."

Phase 2 completion: dialogue's LLM-slot prioritizer now treats an open
ledger promise as significant (continuation pairs genuinely prioritized,
not just allowed to surface); `llm/letters.py` reads `agent.voice`.

Phase 3 first slice, one mechanism per pillar: 3.A "reserved deeper
reasoning" — both LLM clients gained per-call `num_predict_override`/
`temperature_override`, applied only to Innovation Layer propose/
evolve/merge calls via `_schedule_llm_job(deep_reasoning=True)`. 3.B
irreversible personality — `Agent.hardened_traits`/`extreme_event_
count`, three extreme-event triggers (disaster survival, feud/
ostracism, widowhood) lock TRAIT_RESILIENCE against monthly reversion
after `EXTREME_EVENT_HARDEN_THRESHOLD=3`. 3.C audited, not built —
1.A/1.C already ground town_brain with accumulated history; the
map-rendering half flagged as a future follow-up needing live design
judgment. 3.D permanent landscape scars — `World.disaster_scars`,
same shape as `mining_scars`, map overlay + stat tile shipped same
batch.

Verified: direct smoke tests for every new mechanic, a 5000-tick
LLM-disabled engine run with round-trip byte-equality, `scripts/
verify_native_soak.py` (2 seeds x 3000 ticks) byte-identical.

## Current state (v1.3.21)

Explicit user request, three parts: finish 1.D's deliberately-scoped-
out items, add a large pasted "Reflection & Self-Improvement (AI
Scientist)" checklist into the self-evolving vision doc, start Phase 2.

1.D leftovers: storm (no per-tile tracking, unlike flood/wildfire) now
marks every AWAKE agent settlement-wide with a smaller `EMOTION_STORM_
FEAR_BUMP` via `World.tick`'s new `storm_struck` detection; a new
honest "helper" bond (`DISASTER_HELPER_BOND_BUMP`) rewards a bystander
who visibly moved closer to a flood/wildfire tile this same tick — the
non-helper grievance half stays unimplemented (no way to know a
bystander was even aware of the disaster).

Reflection: docs/VISION-2026-07-21-SELFEVOLVING.md gained "Phase 5 —
Reflection & Self-Improvement (the AI Scientist)," a scoped design
(persistent notebook, pattern-detection reflection job, sandboxed
counterfactual harness, offline human-approved recommendations only —
never runtime self-modification) consolidating the pasted ~90-bullet
checklist. Design only this pass.

Phase 2 first slice: dialogue gained five optional structured-outcome
fields (promise/debt_delta/secret_revealed/misunderstanding/
goal_change), mechanically applied to the ledger/agent state by
`Population.apply_dialogue`, plus each speaker's own conflict-capable
`objective` for the exchange (debt > grievance > long_term_goal
priority) grounding the prompt. See CHANGELOG.md's [1.3.21] entry.

Verified: direct smoke tests for all new mechanics, a 4000-tick
LLM-disabled engine run, `scripts/verify_native_soak.py` (2 seeds x
3000 ticks) byte-identical.

## Current state (v1.3.20)

Explicit user follow-up: "Continue Phase 1 with 1.B, 1.C, and 1.D" —
closes Phase 1 of docs/VISION-2026-07-21-SELFEVOLVING.md (the
"self-evolving world" direction, additional layer over the Definitive
Checklist work) for all four co-equal pillars, joining 1.A (v1.3.19).

1.B (Humans): `Agent.long_term_goal`/`life_event_since_goal` — a
standing ambition, revised only at genuine life events (dispute,
death grief, birth) via the existing monthly personal-belief job, zero
added LLM volume; grounds both cognition and personal-belief prompts.
1.C (Village): `Settlement.recent_goal_counts` (via `SettlementCulture`
+ the facade passthrough) — a since-last-check tally of real per-agent
goal decisions, read once by town_brain then reset, so village
cognition reflects aggregate routine behavior, not just discrete
events. 1.D (Nature->Human): `Population._mark_disaster_survivors` —
an agent caught on a flooded/wildfire tile gets a sharp `EMOTION_
DISASTER_FEAR_BUMP` and a causally-tagged memory that graduates to
permanent `core_memories` on eventual eviction; colocated survivors
get a one-time relationship bond. Storm left unwired (no discrete
per-tile tracking yet); the "grievance against non-helpers" half of
the vision doc explicitly not implemented — no disaster-response
mechanic exists to ground it, flagged as a future follow-up.

Verified: direct smoke tests for all three sub-phases, a clean
4000-tick LLM-disabled engine run, `scripts/verify_native_soak.py` (2
seeds x 3000 ticks) byte-identical.

## Current state (v1.3.16)

Explicit user request: "try finishing FT" — docs/archive/AUDIT-2026-07-20.md's
fine-tuning roadmap, FT.3-FT.7. Ships everything buildable without a
second "teacher" model or real GPU training infra (neither exists in
this environment) — FT.3's teacher-distillation half and FT.6 (the
actual training run) stay explicitly flagged as needing external
infrastructure, same "no fine-tuning run itself is implemented"
scoping this project held since FT's prereqs first shipped (v0.87.28).

New modules: `llm/rejection_sampling.py` (FT.3's no-teacher half — k
live LLM calls at a temperature spread, scored by FT.2's labeler,
banked as chosen/rejected DPO pairs; `scripts/rejection_sample.py` is
the CLI), `llm/task_mix.py` (FT.4 sampling-weight math), `llm/prompt_
synthesis.py` (FT.4's synthetic town_brain prompt generator — calls
the REAL `town_brain.build_prompt`, not a fake), `llm/eval_harness.py`
(FT.5 — hash-based train/holdout split, stratified golden set,
tunable regression thresholds over `review_diagnostics.compute_
diagnostics()`). `scripts/recorder_tools.py` gained `synthesize-town-
brain`/`freeze-eval-set`/`check-regressions` subcommands. FT.7: new
`Config.llm_adapter_name` threaded into `TrainingRecorder`'s `dataset`
dict and `/diagnostics`, `None` until a real adapter exists.

## Current state (v1.3.15)

Explicit user follow-up: "try llm_max_concurrent = 1 and the model name
is set inside Hearthmind." Two config changes, no logic change:

- `Config.llm_max_concurrent` 2 -> 1: the v1.3.14 diagnostic showed
  `n_busy_slots_per_decode` 1.88 against 2 configured slots on a
  compute-bound model (~2.6 tok/s) — the same "more slots than the
  hardware can run in parallel" shape as the earlier 3->2 re-tune, one
  notch further for a slower model. One lane means each call gets the
  full compute budget instead of splitting it, directly attacking the
  47-100s call latencies and 30-73s queue waits. `scripts/run.sh`'s
  `LLAMA_PARALLEL`/`LLAMA_CTX_SIZE` defaults moved in step (1, 3072 =
  num_ctx × parallel) — CLI/script defaults must mirror `Config`, per
  the standing rule.

- `Config.llm_model` default `gemma-4-e2b-it` -> `gemma-4-e4b-it`: the
  live diagnostics this whole tuning pass acted on were already running
  the user's actual deployed model (e4b, switched via `--llm-model` at
  the shell), but `Config.llm_model` — and therefore `/diagnostics`'
  `llm_model` field — still read the old 2B default, a real drift
  between "what's running" and "what the code says is running." Making
  the actual deployed model the code default closes that gap for every
  future run that doesn't override it. `gemma-4-e2b-it` stays documented
  (config.py docstring, README) as the smaller/faster fallback.

## Current state (v1.3.14)

Live-diagnostic tuning pass for a slower model (user switched toward
gemma-4-e4b; the pasted `/diagnostics` still read `gemma-4-e2b-it` as
the config default and measured ~2.6 tok/s predicted, p50/p95 call
latency 47s/77s, `llm_pressure_ratio` 1.0 / not paused, and 11,891
backpressure drops against 760 attempts). Two constant changes, no
logic change:

- `scripts/run.sh` `LLAMA_FIT_TARGET` 2048 -> 1024 (explicit user
  request): a smaller `--fit` free-margin offloads MORE model layers to
  the GPU, directly targeting the ~2.6 tok/s throughput floor that
  every downstream number (latency, backlog, drops) bottlenecks on.
  Root-cause lever. Raise back toward 2048 if a fresh `system_memory`
  reading shows the larger offload pushed llama-server into real swap.

- `LLM_PRESSURE_SLOWDOWN_START_RATIO` (engine.py) 1.0 -> 0.75: the
  diagnostic exposed a blind spot — under *sustained* saturation the
  backlog sits pinned exactly at the adaptive limit (ratio 1.0, not
  paused) because excess jobs are cleanly dropped at the gate rather
  than queued past it, so a start of 1.0 never engaged despite the
  drop flood. 0.75 makes a pinned-at-limit backlog stretch the tick gap
  ~2x, halving how fast agents become cognition-due per real second.
  Still no slowdown on a healthy fast-model run (ratio ~0.33).

Adaptive latency thresholds (`ADAPTIVE_LATENCY_ELEVATED/SEVERE_MS`) left
unchanged — the new p50/p95/max (47/77/100s) are near-identical to what
they were calibrated against (32/70/102s), so they're still correctly
sized; the fit-target fix is the real lever. `llm_max_concurrent` also
left at 2 (memory reading was only mildly pressured, ~485MB swap /
2570MB free) — dropping to 1 for faster solo calls on a compute-bound
model is a documented follow-up to try only if latency stays high after
the fit-target change.

## Current state (v1.3.13)

Explicit user follow-up: "try FT.2" — docs/archive/AUDIT-2026-07-20.md's
fine-tuning roadmap, third item.

New `llm/quality_labels.py`: a read-only post-hoc labeler over the
training archive (never mutates it) computing `schema_valid`/`length_
in_bounds` (against FT.0's `json_schemas.py`), `leak_flags` (raw
coordinates, memory-fade prefix, meta-leakage, voice-grammar-break),
`dialogue_responds` (token overlap / question-answered), `topic_novel`
(vs. the prompt's own `settlement_topic` field), and `context_
reflected`, combined into one `sft_eligible` bool. `review_pack.
label_archive()`/`export_sft_filter()` are the entry points —
"the SFT set is a filter query over the archive" — wired into
`scripts/recorder_tools.py` as new `label`/`export-sft` subcommands.

## Current state (v1.3.12)

Explicit user follow-up: "ship FT0 and FT1" — docs/archive/AUDIT-2026-07-20.md's
fine-tuning roadmap, first two items.

FT.0: `llm/json_schemas.py` gives the eleven highest-volume LLM tasks
(everything a real archive's `task_distribution` actually shows) a
real JSON Schema; `LlamaCppClient`/`OllamaClient.generate_json` and
`CognitionRunner.run` gained an optional `json_schema` param, wired at
all four `_cognition_runner.run` call sites. llama-server enforces the
schema as a GBNF grammar — required keys, types, and enums (`goal`,
`sentiment`, `priority`) are now sampler-level guaranteed, not just
"valid JSON." `None` for any task outside the eleven keeps the old
unconstrained `json_object` behavior untouched.

FT.1: the prompt fixes it depends on (P0.1/P0.2/P0.4/P1.1) were
already shipped; `TrainingRecorder.start()` now auto-appends
`hearthmind-<version>` to `session_tags` so every future recording
session is unambiguously version-tagged without relying on an
operator to type one in — closes the "mark the epoch boundary with a
tag" gap that was previously purely aspirational.

## Current state (v1.3.11)

Explicit user follow-up: "Do the eyeball pass and make the call [on
P1.4] and also finish P3." Closes `docs/archive/AUDIT-2026-07-20.md`
entirely — every P0/P1/P2/P3 item shipped, only the FT fine-tuning
roadmap remains (a scoped future effort, not a checklist item). Full
detail: CHANGELOG.md.

P1.4 verdict: NOT pruning `mind_text` from cognition prompts. A live
review pack's low reflected-rate (10.3%) was mostly an artifact of
P1.3's not-yet-live forced-choice call volume (69% of that pack's
cognition examples), not a real prompt problem — eyeballing the
remaining genuine open-decision examples found `mind_text` clearly
shaping reasons even without lexical overlap. Re-measure from a
post-P1.3 archive before revisiting.

P3.1: recorder status omits `sample_rate` outside `SAMPLED` policy.
P3.2: a new spreading-verbal-tic detector (`dialogue.is_spreading_
tic`) degrades a line whose tail phrase has already been used by 3+
other speakers to the deterministic fallback. P3.3: dialogue's
SYSTEM_PROMPT (already carrying 5 connected exemplars) gained one more
sentence naming the specific observed non-sequitur failure mode. P3.4:
`/diagnostics` gained `dialogue_topic_share`/`mood`/`materials_flow_
per_tick`/`cognition_context_reflection_rate` — four numbers the audit
had to compute by hand, now live in the same payload the dev console
already polls.

## Current state (v1.3.10)

Explicit user follow-up: "Continue with P2 items from the audit and
P1.3." Ships P1.3 (previously flagged v1.3.7 — explicit instruction
now supersedes that flag) and all five P2 items from `docs/archive/AUDIT-
2026-07-20.md`. Full detail: CHANGELOG.md.

P1.3: forced-choice cognition (hunger/energy past their survival
thresholds) skips the LLM call entirely now — the goal was never a
real choice at that point, only the reason-authoring call is removed.

P2.1: predator-pack recolonization was gated on exactly-0-packs (a
pack thinned to 1 got no help) — now target-fraction-based like
grazers, fixing a real measured ecology-trending-empty collapse.

P2.2: the disease outbreak floor was population-independent and kept
reseeding new cases mid-outbreak — now skipped once sick fraction
exceeds 15%, so a small village still gets its guaranteed first case
without staying artificially sick forever.

P2.3: `terrain_reclaimed` events batch per-call instead of per-tile;
`surveyor_finding` demoted from the main event feed (still reachable
via the Exploration stat tile).

P2.4: settlement belief revision now re-surfaces subject-relevant
lived evidence (soil/harvest/food keyword families) already present in
the event window, so a stale belief has something to actually contend
with.

P2.5: town-brain's prompt restates its objective stat block
immediately before the ask instead of only at the top, and requires
the rationale to cite an actual number.

## Current state (v1.3.9)

Explicit user follow-up: "Complete P1 fully" — the three remaining
`docs/archive/AUDIT-2026-07-20.md` P1 items. P1.3 stays deliberately flagged,
not shipped (reverses an earlier explicit design decision, needs a
user call). Full detail: CHANGELOG.md.

P1.2: `llm_max_concurrent` 3 -> 2 (a live `n_busy_slots_per_decode`
2.58 against 3 slots showed the third mostly adds contention);
dialogue/rumor_interpret now shed backpressure load before cognition
does (`DIALOGUE_BACKPRESSURE_FRACTION=0.75`/`RUMOR_INTERPRET_
BACKPRESSURE_FRACTION=0.5`, `simulation/engine.py`) — previously all
three used the identical bare threshold despite dialogue being
commented "most expendable."

P1.4: `llm/review_diagnostics.py`'s Context Influence section gained a
per-field `by_field` breakdown (offered count + reflected rate per
context-thread key), the measurement step the audit asked for before
any pruning decision — the prune/rotate action itself is left for a
future pass once a real archive's numbers exist to act on.

P1.6: new `CORE_CAST_POPULATION_FRACTION=0.4` caps the seat count
passed to `maintain_core_cast` at `min(llm_core_cast_size, ceil(
population * 0.4))` — a small founding party gets a proportionally
small core cast instead of the fixed 18 driving 75%+ of everyone
through LLM cognition. Scoped to this fraction cap only; throughput-
derived sizing and the Tier 1/2/3 + spotlight scheme remain backlog.

## Current state (v1.3.8)

Explicit live-report follow-up, two-part request: diagnose a
400-population/1590-structure world stuck at zero inventions and
`stone_age`, and replace the flat `POPULATION_CAP=400` with a
map-size-scaled cap. Full detail: CHANGELOG.md.

Root cause of the invention stall: `invention` was the one job
deliberately excluded from `SEASON_YEAR_JOBS_WITH_RETRY` (its own
per-occurrence RNG roll made a naive retry window inflate the real
odds) — under this world's real backpressure (598 dropped calls),
that single-exact-tick gate meant its one seasonal roll per settlement
had a real chance of landing on a backpressured tick and losing the
whole season silently. Fixed by adding `invention` to the retry set
and moving `_mark_season_year_resolved("invention")` to fire right
after the backpressure check clears but before the RNG roll — the
roll still happens at most once per season, a backpressured attempt
just no longer burns that one chance.

New `dynamic_population_cap(map_tiles)` (`agents/agent.py`,
`POPULATION_DENSITY_PER_TILE=0.1`, bounded [`POPULATION_CAP_FLOOR=
100`, `POPULATION_CAP_CEILING=3000`]) replaces the flat `POPULATION_
CAP` as `carrying_capacity()`'s final ceiling whenever a caller passes
map area — `World.tick()` now does, via `map_tiles=config.width *
config.height`. Default 64x64 map's cap (~410) stays close to the old
400 so existing tuning expectations hold at default map size; a
larger map gets real headroom (up to 3000), a smaller one a floor
(100). `POPULATION_CAP` itself stays as the fallback for any caller
that doesn't pass map area.

## Current state (v1.3.7)

Explicit user follow-up: "do the next part from audit" — continuing
`docs/archive/AUDIT-2026-07-20.md`'s P1 backlog. Shipped P1.1 (three
simulation-scaffolding leaks into the fiction: raw tile coordinates
recited in speech, `faded_memory_text`'s "I only vaguely recall:"
prefix quoted/laundered as literal dialogue, `grounded_event` always
being the single most recent event and feeding P0.2's monoculture —
now a weighted top-5 pick) and P1.5 (duplicate place names — prompt
now lists names already in use, `parse_name` rejects a collision).
P1.3 (skip the LLM call during forced-priority hunger/exhaustion)
deliberately NOT shipped — it reverses an earlier explicit decision
(`critically_hungry` agents are flagged triggered specifically so a
crisis "deserves the LLM's actual reasoning," not just deterministic
text) and needs a user call, recorded as flagged-not-shipped in the
audit doc rather than changed unilaterally. Full detail: CHANGELOG.md.

## Current state (v1.3.6)

Explicit user request: implement an uploaded external audit
(`docs/archive/AUDIT-2026-07-20.md`, added this pass — full P0-P3/FT backlog,
checkboxes updated as items ship) and check off shipped items. All
four P0 items landed: (1) mood pinned negative — `tick_mood`'s
`signal = avg*2-1` mapped calm to -1 on every axis, fixed to
`signal = avg`; (2) discourse monoculture — dedupe the per-pair topic
ring, gate rumor spread/InterpretRumor() on topic novelty
(`RUMOR_NOVELTY_MIN_COUNT=3`), add `terrain_reclaimed`/`terrain_
thinned` to `ROUTINE_EVENT_CATEGORIES` (14 consecutive lines had been
flooding a beliefs prompt); (3) construction starvation — new
`materials_critical` flag (stockpile below `cheapest_founding_cost()`)
threaded into both the cognition grounding line and, more importantly,
`fallback_goal` (most GATHER decisions never reach the LLM path at
all), force-selecting GATHER the way hunger/energy already force
FORAGE/REST — scoped to the audit's cheaper options, not the full
civic-reservation mechanism; (4) broken voice grammar ("Ysolde Always
speaks...") — new `agents.agent.normalize_voice_phrase()` applied at
both write time and every read, retroactively fixing already-
persisted voices with no snapshot migration. P1-P3 and the FT
fine-tuning roadmap are recorded in the doc as standing backlog. Full
detail: CHANGELOG.md.

## Current state (v1.3.5)

Explicit user follow-up: "improve the context influence numbers."
Per-example inspection of the 3rd review pack's `structured_input`
found the real cause was context *supply*, not prompt wording: 97% of
cognition calls had `mind_text` but 82-100% had every other optional
field (`own_belief`/`semantic_memory`/`life_digest`/`lesson`/
`core_memory`/`institution_objective`/`plan_intent`) empty. Two fixes:
(1) `_author_minds`'s "never retries" backpressure drop (deliberate,
v0.78.4) left some core-cast members permanently on the generic
fallback identity text — new bounded FIFO retry queue (`_pending_mind_
agent_ids` + `_maybe_retry_mind_authoring`, one retry/tick, same
backpressure/budget gates as everything else) instead of giving up
forever. (2) `_maybe_schedule_personal_belief` (Reflect(), the only
source of those other fields) picked one agent/month against an
18-member core cast — `PERSONAL_BELIEF_PICKS_PER_MONTH=2` widens this
to two, still a fixed population-independent monthly count. `cognition.
py`'s own prompt wording left unchanged this pass — this targets supply
of distinctive context, not how the model uses it. Full detail:
CHANGELOG.md.

## Current state (v1.3.4)

Third review-pack audit, first one confirmed running actual current
code (`hearthmind_version: "1.3.3"` in its own diagnostics) — v1.3.1's
forage/gather fix visibly working live in its sample cognition call.
Real bug found: `beliefs.py`'s theory-revision jobs (settlement,
per-agent, and institution) trusted a `revises` answer unconditionally
even when the returned belief text/confidence were byte-identical to
the entry being "revised" — logging a `belief_revised` event and
archiving a no-op "previous version" for a call that changed nothing.
Same shape as folklore's v1.3.2 fix: new `beliefs.is_noop_belief_
revision()` (Jaccard word-overlap + unchanged-confidence gate) wired
into all three call sites. Full detail: CHANGELOG.md.

## Current state (v1.3.3)

Explicit user request off the pasted live diagnostics: fix backpressure
drops wasting system resources/LLM calls. Root cause: `_reserved_this_
tick` (v0.81.0's same-tick reservation fix) only cleared at the TOP of
the next `_tick_once` — fine when ticking ran continuously, but LLM-
pressure pacing (v0.82.0, added later) can pause ticking for extended
real time, during which that tick's reservation count never clears
while `CognitionRunner.backlog` correctly keeps counting the same jobs
once they actually start — `_effective_backlog()` then double-counted
one in-flight batch for the whole pause window. Live evidence: `llm_
backlog_effective` 20 = `background_tasks` 10 + `llm_backlog_reserved_
this_tick` 10, the same 10 jobs twice, inflating `llm_pressure_ratio()`
from a real ~1.11 to 2.22 and tripping the pause threshold (2.0)
unnecessarily — which also fed the same-limit checks that drop calls.
Fixed by also clearing `_reserved_this_tick` right after `_tick_once`'s
own scheduling loop finishes, not just at the next tick's top. Full
detail: CHANGELOG.md.

## Current state (v1.3.2)

Follow-up review-pack audit, same live world (51,922 ticks), with a
live `/diagnostics` snapshot pasted alongside it. That snapshot's
`training_recorder.dataset.hearthmind_version` reads `"0.87.46"` —
**this deployment hasn't picked up any of this session's v0.88.0-1.3.1
work**; several things that would otherwise read as new bugs (missing
Context Influence diagnostics, low personality diversity, the forage/
gather mislabeling) are that already-fixed backlog still running live,
not new findings — restart the deployed server on current code.

Real new bug found: `llm/folklore.py` had the same feedback-loop shape
`Settlement.top_topics()` had for dialogue (fixed v0.87.35) — showing
the model its own last 5 tales as context with no instruction to
differ from them, so a settlement with one dominant recurring rumor
theme got near-identical restatements of the same legend nearly every
month. Fixed via a `SYSTEM_PROMPT` instruction plus a deterministic
Jaccard word-overlap backstop (`parse_folklore`'s new `existing_tales`
param, `FOLKLORE_DUPLICATE_OVERLAP=0.6`) — a near-restatement is now
discarded as "nothing new" instead of stored. Full detail: CHANGELOG.md.

## Current state (v1.3.1)

Explicit user request: audit a real uploaded review-pack export (500
examples, one live run) and find concrete cognition/intelligence/
learning/emergence improvements. Found and fixed a real bug: past
`SURVIVAL_HUNGER_THRESHOLD` the model was supposed to echo the forced
priority back as `goal: "forage"` but `SYSTEM_PROMPT` never defined
what `'forage'` meant, so it overwhelmingly returned `"gather"` instead
while narrating hunger in `reason` — real movement impact for the
0.6-0.9 hunger band (below `CRITICAL_HUNGER_THRESHOLD`'s movement-layer
override), not just cosmetic. Fixed by defining `'forage'` in the
prompt AND enforcing the forced goal server-side in `SimulationEngine.
_apply_pending_cognition_results` (same "not a real LLM choice past
threshold" reasoning as v0.87.15) rather than trusting a small model to
self-report correctly. This pack's own diagnostics also carried a
data-freshness caveat (empty Context usage section, no Context
Influence section, old 15-word reason cap) indicating it predates
v1.3.0 — noted so its findings aren't misread as measuring that fix.
Full detail: CHANGELOG.md.

## Current state (v1.3.0)

Explicit user request: "improve context utilization" — cognition
prompts already supply rich context, but generated `reason` text often
reflects only the loudest cue (hunger) rather than synthesizing what
else was given, even when a real person would weigh several things at
once. `llm/cognition.py`'s `SYSTEM_PROMPT` now explicitly asks the
model to weigh ≥1 thing beyond the obvious need when the prompt offers
more than one, with a worked example of what blended real-person
reasoning sounds like versus a forbidden step-by-step/numbered listing
(no exposed chain-of-thought). `reason`'s word cap raised 15 -> 28 (a
slight, acceptable token uptick, not the goal itself). New measurable
counterpart: `SimulationEngine._schedule_due_cognition` now captures a
`context_snapshot` (every optional text context thread actually
offered this call) into the recorder's `structured_input`; new `llm/
review_diagnostics.py` "Context Influence" diagnostic — a stdlib-only
lexical-overlap heuristic reporting avg context threads referenced per
example and the direct "multi-context synthesis rate" (≥2 threads),
surfaced in every review-pack export. Full detail: CHANGELOG.md.

## Current state (v1.2.0)

Post-v1 follow-up, second of two chosen items ("inventions unlock
specific things"). Every invention used to have the identical
mechanical effect (flat `tech_level += 1`) regardless of what the LLM
named it. `llm/invention.py` now also picks a closed-choice `category`
(agricultural/structural/mercantile/general, `buildings.INVENTION_
CATEGORIES`) alongside the free-text name/description — same closed-
choice-on-top-of-open-creativity shape `era_branch.py` established.
Each matching invention nudges a small, capped (`INVENTION_
SPECIALIZATION_CAP=0.18`) settlement bonus consumed multiplicatively
via new `Population._specialization_factor` at category-matched sites
(agricultural: farm/husbandry yield; mercantile: workshop/factory/
dock/oil_rig/forge/banker income; structural: construction/repair work
rate) — stacks with, doesn't replace, the existing flat `_tech_factor`.
"medical" deliberately deferred (higher blast radius). New "Invention
specializations" UI panel. Full detail: CHANGELOG.md.

## Current state (v1.1.0)

Post-v1 follow-up, explicit user request after the batch shipped:
core-cast rotation, the convergence audit's top still-open finding.
`Population.core_agent_ids` (the fixed LLM-authorship cast) was
permanent — no living member was ever demoted, so every emergent
storyline funneled through the same ~14 characters forever. New
`_maybe_rotate_core_cast` (monthly, deterministic, zero added LLM
volume): swaps the weakest core member for a clearly more prominent
outsider (`CORE_CAST_ROTATION_MARGIN=1.5x`) with a bounded monthly
chance (0.15). Deliberately rare/sticky, not a repeal of "never
demoted while alive" — a real exception to it. Outgoing members keep
their full history; they just stop getting new core-cast-gated jobs.
Logs a `core_cast_rotation` event. Full detail: CHANGELOG.md.

## Current state (v1.0.0) — first major-version bump

Closes the five-phase v1 batch (v0.88.0-v0.91.0, this file's four
entries directly below) launched by an explicit "audit the code again
very carefully and in depth... this will be the first v1 bump"
request. Four parallel research passes (CA/deterministic systems, LLM
prompts incl. genesis, era/invention math, convergence/emergence)
found the bug list closed in Phase 1; genesis overhaul in Phase 2; the
full ten-era ladder in Phase 3; LLM branching influence in Phase 4.
Verified end-to-end via a 20,000-tick soak (LLM disabled) confirming
the whole batch integrates cleanly and round-trips through snapshot
save/load. Full detail: CHANGELOG.md's [1.0.0] entry and the four
phase entries below it.

## Current state (v0.91.0) — v1 batch, Phase 4

Explicit user ask: let emergence/LLM steer its own course of era
progression. Scoped to branching influence, not literal LLM-invented
eras — `ERA_ORDER`/thresholds stay fully deterministic; a new `llm/
era_branch.py` job fires once per era advance and picks one of five
named branches (industrious/scholarly/devout/mercantile/agrarian) from
a closed list, biasing `choose_building_kind`'s odds toward that
character (`ERA_BRANCH_BOOST=1.35x`, smaller than the seasonal
priority boost). Two settlements on the same tech path can now diverge
visibly in building mix. `Settlement.era_branch` persisted, surfaced
inline on the Era stat tile. Full detail: CHANGELOG.md.

## Current state (v0.90.0) — v1 batch, Phase 3

Explicit user ask: more intermediate eras following human history +
less harsh progression. `ERA_ORDER` extended from 4 to 10 eras
(`stone_age -> bronze_age -> iron_age -> classical -> medieval ->
renaissance -> industrial -> electrical -> modern -> digital`);
settlements now start `stone_age`, not `industrial`. Thresholds
rebalanced so a new era arrives roughly every 1-3 inventions across the
whole ladder rather than the old 4-era scheme's sparser milestones.
Two new buildings (FORGE bronze_age+, LIBRARY classical+) and two new
occupations (BLACKSMITH, SCRIBE) reuse the existing WORKSHOP/SCHOOL
production-bonus shapes exactly — zero new mechanism types. Full
detail: CHANGELOG.md.

## Current state (v0.89.0) — v1 batch, Phase 2

Explicit user ask: "improved genesis prompt." Root cause of the real
weakness: the LLM's scenario text used to be hashed into the world's
RNG seed, meaning it was always written before any terrain existed —
so a narrated "river valley" had no guarantee of a real river nearby.
`server.py` now generates a real preview terrain from its own entropy
first, describes what's actually near spawn (`world_genesis.detect_
terrain_features`), feeds that into the prompt, and returns that same
entropy as the final seed — the terrain the real world gets is now
mathematically guaranteed to be the terrain genesis described.
`seed_from_scenario` removed (no longer called). New `_SETTLER_
CIRCUMSTANCE_HINTS` axis (independent of the terrain lean) gives the
model something to say about who the founders are, not just the land.
Full detail: CHANGELOG.md.

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
`docs/archive/VISION-2026-07.md`'s "nothing implemented yet" header and this
file's own "Nothing from this vision is implemented yet" (both false —
Phases I-N have been fully shipped since v0.84.4) and the §8 summary
below ("not-yet-scoped... work from it only on future explicit
direction" — false, two of three items shipped). Trimmed docs/archive/
VISION-2026-07.md and docs/archive/VISION-2026-07-LEARNING.md to status
pointers, same treatment docs/archive/ROADMAP.md already had. Consolidated
this file's own "Current state" history (v0.82.0-v0.87.26 folded into
the existing "Consolidated history" section, which now spans v0.65.2-
v0.87.26 as one themed block) — 3013 -> ~1040 lines, same periodic
maintenance as the v0.63.0/v0.85.0 passes. docs/archive/IDEAS-2026-07-
EMERGENCE.md/docs/REFACTOR-2026-07.md/docs/archive/REVIEW-2026-07.md/docs/
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
every remaining unchecked item in docs/archive/IDEAS-2026-07-EMERGENCE.md §9
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

§9's last item (docs/archive/IDEAS-2026-07-EMERGENCE.md, "stalled era
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

§8's third item (LoRA/QLoRA fine-tuning, docs/archive/IDEAS-2026-07-
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
IDEAS-doc section number, docs/archive/IDEAS-2026-07-EMERGENCE.md's own
per-item writeup) — this section keeps only durable facts (mechanisms
still active, constants still in force) so CLAUDE.md stays a working
reference, not an archive. Consolidated/extended 2026-07 per explicit
user requests ("trim all the docs..." then later "clean up stale docs
and stale items").

**"The LLM learns like a human" (v0.87.0–.4)**: fully shipped, see
docs/archive/VISION-2026-07-LEARNING.md (trimmed to a status pointer) for the
complete mechanism list — `Agent.lessons`, memory drift, salience
fade, cross-generational lesson inheritance, LLM-narrated skill
mastery, settlement pattern-beliefs, consciousness player-theory
revision, trait-consequence nudges.

**docs/archive/IDEAS-2026-07-EMERGENCE.md §1-§9 implementation (v0.87.7–.31,
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
- The full architecture review lives in `docs/archive/REVIEW-2026-07.md`; its
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
