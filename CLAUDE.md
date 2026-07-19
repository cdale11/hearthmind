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
loop workflow rule below and "Current state (v0.86.0)").

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

**`docs/IDEAS-2026-07-EMERGENCE.md`** (filed v0.87.6): an externally-
submitted, checked-against-the-code "what's still missing" audit —
idea checklist only, nothing implemented or green-lit, tracked the
same way this vision doc is. Its own §0 audits which of an outside
~50-item wishlist is already shipped vs. genuinely missing; §1-§6 are
original ideas (agent action-vocabulary gaps, inter-settlement wants,
meaning-loop closure, observer-aware consciousness, deep-time
legibility, substrate); §7 is specifically the wishlist's real gaps
(adaptive retrieval, causal memory, episodic planning, emergent
leadership, per-agent voice, knowledge lifecycle, laws/customs,
institution objectives, dialogue novelty memory — the llama-server
`/slots`/`/metrics` item there shipped in v0.87.6, see below); §8
(added v0.87.22, explicit user request) tracks three not-yet-scoped
ideas outside the doc's original outside-review shape: fine-tuning the
local model (LoRA/QLoRA) on Hearthmind's own generated prompt/
completion data with human-supervised top-5%/worst-5%/random-1%
curation before any training batch; NPC/environment activity
reshaping geography further (visible mining scars, quarrying,
settlement-driven terrain change beyond the existing deforestation/
road-wear mechanics); and an expanded mineral/material economy (gold,
iron, diamonds, silicon, etc., extending the single undifferentiated
`ResourceKind.ORE`) explicitly in service of NPCs believing they live
in a real world, not just more numbers. Work from it only on future
explicit direction, same as this vision doc.

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

## Current state (v0.87.26)

§8's mineral economy (docs/IDEAS-2026-07-EMERGENCE.md, explicit user
directive), per explicit sequencing ("except lora do everything
sequentially" — minerals first, geography reshaping next, LoRA
fine-tuning left recorded-only). New `world/minerals.py`
(`MineralGrid`): distinct IRON/GOLD veins on HILLS, deliberately a
standalone module rather than a `ResourceKind` extension —
`ResourceGrid`'s native tick path switches on a closed kind-string set,
and extending it without touching C++ risked silently wrong regen or a
crash. Flagged R7 deviation (same shape as v0.87.23's spatial weather).
GATHER-goal agents on a deposit-bearing tile work it in place of plain
materials into `Settlement.minerals`, capped at `MINERAL_CAPACITY=8.0`
per kind; extends (not duplicates) two existing systems — iron
sweetens H4's tools chain, both sell for far more than materials at
the existing overflow-to-currency mechanic. DIAMOND (MOUNTAIN)/SILICON
(BEACH) explicitly deferred — need real GATHER pathing work
`_nearest_material_tile` doesn't do today (`MATERIAL_BIOMES` is
FOREST/HILLS only), a larger increment. New "Minerals" UI stat tile.

## Current state (v0.87.25)

Direct follow-up to v0.87.24's starvation work, mid-turn explicit user
request: "the starvation fix shouldn't just come from granaries and
agriculture, they should actively seek out new ways to get food like
husbandries (milk, eggs, meat), hatcheries (fish), foraging... and
other sources." Audited: PASTURE/HATCHERY (v0.86.7) already produced
food, and wild foraging was already the last-resort fallback — the
real gap was that nothing ever deliberately PATHED a hungry agent
toward a pasture/hatchery, or an idle agent toward tending one; both
only ever worked by lucky colocation. `stocked_granary_positions`
widened to include stocked PASTURE/HATCHERY as FORAGE targets; new
`husbandry_positions` folded into `work_positions` (the WANDER-goal
attractor) so idle well-fed agents seek out tending them. Movement-
layer only, no new state.

## Current state (v0.87.24)

Explicit user directive: starvation was reported as the dominant,
near-universal population-collapse mode across playthroughs and needed
an aggressive fix; separately, header/stat UI clutter needed reducing
without removing any existing stat.

**Starvation root cause (measured, not guessed)**: `Population.
carrying_capacity`'s only food-supply signal (granary_fill) required a
standing GRANARY to engage at all, and `_maybe_reproduce`'s surplus
gate only read the reproducing PAIR's own momentary hunger, never the
settlement's aggregate state — population could grow on housing supply
alone while food production silently fell behind, with no graceful
brake short of mass death. A baseline 40k-tick no-LLM soak (seed 7)
confirmed it: population grew to 29 then crashed to 2, 70 starvation
deaths, 0 old-age deaths (starvation was structurally the only death
this settlement could reach). Fixed with five changes together:
`CARRYING_CAPACITY_HUNGER_WEIGHT`/`_HUNGER_COMFORT` (new, always-on
average-hunger term in `carrying_capacity`, no granary prerequisite);
`REPRODUCTION_SETTLEMENT_HUNGER_CEILING` (new hard backstop — no births
while the settlement's own average hunger is elevated, regardless of
the parents' state); `GRANARY_CAPACITY` 15.0 -> 40.0 (the old value
measurably drained to 0.0 in under a sim-day at any nontrivial
population — no real buffer); `HUNGER_RATE` 0.01 -> 0.008 (widens every
reactive food-seeking threshold's real margin proportionally);
`STARVATION_TICKS_TO_DEATH` 200 -> 280 (more grace once critical). Two
tuning passes, both measured: first pass (weight 0.4/comfort 0.35/
ceiling 0.55) re-tested clean on seed 7 (plateaued at 44, never dropped
below ~20, old age (24) overtook starvation (13) for the first time)
but seed 23 showed it was still too loose (overshot to 62, crashed to a
low of 8, starvation (72) still dominant — better than baseline's crash
to 2, not the reversal asked for). Second pass tightened further
(weight -> 0.55, comfort -> 0.28, ceiling -> 0.45) — seed 23 STILL
crashed (overshot to 92, dropped to 13, starvation 46 vs old age 19).
Investigated whether the hunger term's own floor was the limiter:
lowered `CARRYING_CAPACITY_MIN_MULTIPLIER` 0.5 -> 0.3 to give it more
room against a settlement that had already out-built its food supply —
the re-run came back BYTE-IDENTICAL to the 0.5 run, proving the
capacity floor was never actually binding in this crash. Reverted.
Real diagnosis: `REPRODUCTION_SETTLEMENT_HUNGER_CEILING` had already
blocked every new birth once average hunger crossed 0.45, so the crash
(92 -> 13) was pure EXISTING population starving once a sudden shock
(avg hunger 0.35 -> 0.72 in ~4,000 ticks, a seasonal/weather-driven
food dip) hit a settlement too large for its granary to buffer — no
demand-side throttle can undo an already-large population's food need.
Fourth change: `GRANARY_CAPACITY` 40.0 -> 90.0. Re-run on seed 23: STILL
crashed (peak 103, low 13, starvation 48 vs old age 18) — the granary
bump didn't meaningfully change this seed's outcome either.
Investigated why: this settlement's `farms_total` peaked at only 18 for
a population of 103 — its actual FOOD PRODUCTION capacity, not the
granary buffer, is the binding constraint on this particular map.
**Stopped tuning here** rather than keep chasing one seed's map
geography with global constants (risks overfitting at every other
world's expense). Net result: seed 7 fully fixed (clean plateau, old
age now dominant); seed 23 substantially improved over the true
baseline (recovers to a healthy population every run, never craters to
near-zero with no path back) but still shows a starvation-heavy
boom-bust cycle when growth outpaces that map's farmable land — a
genuine food-PRODUCTION gap distinct from the food-DEMAND gap this pass
closes. All five demand-side changes are kept (individually verified
effective); closing the supply-side gap the same way — e.g. tying
construction pace or a more aggressive `_maybe_plant` response to a
measured farms-per-capita ratio — is flagged as the natural next
increment, not attempted this pass.

**UI declutter, stats preserved**: the header's 12 always-visible
toggle buttons collapsed into 4 (`details` stays top-level; `🔭
explore ▾` groups summary/chronicler/digest/highlights/history/
timeline/relationships; `⚙ view ▾` groups subjective/ambience/dev).
Hit the exact `.hidden`-vs-same-specificity CSS landmine this file
already documents for `.consciousness-indicator` (v0.82.0) — fixed the
same way, `:not(.hidden)`. The details panel's ~30 raw stat tiles
gained six section labels (Time & weather / Population & society /
Settlement & infrastructure / Economy / World & environment / AI,
trade & diplomacy) instead of one flat grid — same tiles and values,
just grouped for readability.

Verified: direct production-path tests for both new gates; five
40,000-tick no-LLM soaks total isolating exactly which tuning changes
helped, which did nothing (confirmed byte-identical), and which hit a
genuine map-specific limit; live Playwright verification of both header
dropdowns and the grouped stat-grid, zero console errors.

## Current state (v0.87.23)

Two parts per explicit user request: implement everything still open
in docs/IDEAS-2026-07-EMERGENCE.md's original outside-review sections
(§6 "Substrate" + the last piece of §7), and record 12 new culture/
institution/reputation/era-progression ideas as an unimplemented
checklist (§9).

**Spatial weather**: `World.weather_regions` (3x3 coarse grid,
`WEATHER_REGION_GRID`), each region computed via the same `compute_
weather` with its own deterministic seed offset. Deliberately Python,
not C++ — a documented, flagged deviation from R7's "new code in this
domain is C++ from the start" default given this batch's multi-item
scope; native-porting under R6 is a flagged follow-up if it proves
worth it. `World.weather_at(pos)` resolves a settlement's own region;
`Settlement.tick`'s building-decay catalyst now reads it (two
settlements genuinely decay at different rates), surfaced as
`local_weather` per settlement in `/state`. Farms/wildlife/disasters
stay on the single global `World.weather` — documented scope trim.

**Soil fertility**: `FarmGrid.soil_fertility` (per-tile 0..1, floor
0.4, tracked only for ever-farmed tiles — bounded). Depletes under an
active plot, recovers (2x rate) fallow, read at `plant()` to scale the
new plot's `max_yield` — continuous re-planting now yields measurably
less than resting a tile.

**Ambient audio**: client-side only, off by default ("🔊 ambience"
header toggle). Two detuned oscillators + lowpass filter, all
parameters smoothly ramped from `night_factor`/`weather_detail`
(already public) and settlement `temperament` (Phase G — read, never
surfaced as a number/word, same discipline the map already applies).

**Queue-wait-per-job diagnostic**: `CognitionRunner.stats()`'s new
`queue_wait_ms_p50`/`_p95` closes §7's llama-server-diagnostics item
(`/metrics` polling + `retrieval_diagnostics()` shipped earlier;
`/slots` stays a deliberate non-goal, can leak prompt content).
Distinguishes "semaphore-starved" from "model/server is slow."

**§9 checklist** (docs/IDEAS-2026-07-EMERGENCE.md, NOT implemented):
12 items — topic/rumor diversity, institutions' own persistent memory,
deceased-agent/family reputation legacy, multi-layer culture,
competing narratives, geography-in-dialogue, sim-grounded dialogue,
cross-system cascades, long-term societal evolution, and a root-caused
(not just proposed) diagnosis of stalled era progression: `era_for_
tech_level` gates purely on `tech_level`, incremented only by a rare
seasonal invention roll with zero infrastructure-count floor — a
settlement can sit at `industrial` forever regardless of huts/roads/
schools/carts built. Two items (emotional/importance-based memory
retrieval, relationship pruning) were found already fully shipped
(v0.87.14; decay-to-zero relationship fix) and flagged as such rather
than re-listed.

Verified: direct production-path tests for all four implemented
pieces (regional weather distinctness/round-trip/fallback; soil
fertility depletion+recovery against floor/ceiling; queue-wait under
real concurrent contention). `scripts/verify_native_soak.py` (3 seeds
x 3000 ticks) byte-identical — no native module touched. A 2-seed x
20,000-tick organic engine soak (LLM disabled) completes with zero
crashes across both seeds.

## Current state (v0.87.22)

Direct follow-up per explicit user request ("continue" after a
routine/trigger-scheduling attempt for §5/§6 hit a tool-approval
error) — closes all five items of docs/IDEAS-2026-07-EMERGENCE.md §5
("Making deep time legible"), observer-side and mostly zero-LLM.

**"While you were away" digest** (new `llm/digest.py`, `World.away_
digest_*`, `GET /digest`/`POST /digest/request`): on-demand, same
enqueue-now/apply-next-tick seam as `sim_summary`/`chronicler`. New
`persistence/snapshot.py:events_since_tick` windows by TICK RANGE
(not row count) since the previous digest's boundary, headlined by
whatever touches agents the observer has actually inspected
(`SimulationEngine._watched_agent_names`, reusing v0.87.21's `World.
observer_attention`).

**Anomaly/highlight log** (`World.highlights`, capped
`HIGHLIGHTS_MAX_STORED=30`, `GET /highlights`): `_append_highlight`
fires from hand-picked triggers (first religion, first ritual, feud
formation) and a rolling z-score over daily population riding the
existing `_log_daily_metrics` cadence, plus a genuine extinction-
near-miss edge. Not shipped: "belief flipping true to false" — no
truth-value field exists on beliefs yet, flagged as a follow-up.

**Year-reel export** (client-side only): "🎬 export year reel" button
drives the existing timeline replay loop while recording the map
canvas via `MediaRecorder`, downloads a `.webm` — zero backend
changes.

**Ruins mode / successor worlds** (`SimulationEngine._found_
successor_world`, `POST /world/found-successor`): scoped to "true
extinction" (population 0) only — "or by choice" while alive flagged
as a follow-up (needs a living-relocation mechanism this doesn't
build). Founds a genuinely new `Settlement` on the SAME terrain/roads/
wildlife/farms; the defunct settlement is KEPT (never discarded — same
"the settlements list never shrinks" stance already documented above),
so its ruins/memorials/records/place_names/religion simply keep
existing. New `Settlement.predecessor_id`; `llm/beliefs.py` folds in
one optional grounding line quoting the predecessor's newest written
record (or "no one knows why it fell silent" if none survive) — the
new population may honestly misread it. New `Population.spawn_
successor_founders` (mirrors `spawn_initial`'s site-selection, but
appends into the existing extinct `Population` so cumulative history/
`_next_id` isn't discarded — new founders' ids never collide with a
departed agent's id still referenced in the durable memory-log
tables). New "💀 the world is empty" banner + "🏚 found a successor
settlement" button, population-0-gated.

**Era-styled cartography** (client-side only): the map's rendering
style ages with the era system — a deterministic stipple overlay for
industrial/electrical eras, a clean surveyed grid line overlay for
modern/digital. Repainted in place on `era_advance` events.

Verified: direct production-path tests for all five pieces (tick-range
event windowing; a real `_schedule_away_digest` call resolving through
its actual fallback path; highlight append + forced extinction-near-
miss detection; a real `_found_successor_world` call confirming new-
settlement/predecessor_id/founder-settlement_id/refusal-when-not-
extinct against actual production code; a forced `_maybe_schedule_
beliefs` call with a fake LLM client confirming the ancestor-ruins
line reaches a real built prompt; round-trip serialization).
`scripts/verify_native_soak.py` (3 seeds x 3000 ticks) byte-identical
— no native module touched. A 2-seed x 20,000-tick organic engine
soak (LLM disabled) completes with zero crashes across both seeds.

**Not yet started**: §6 ("Substrate" — spatial weather, soil fertility,
ambient audio), the last unimplemented section of docs/IDEAS-2026-07-
EMERGENCE.md.

## Current state (v0.87.21)

Direct follow-up per explicit user request ("Build item 4 and item 7
stale tasks") — closes docs/IDEAS-2026-07-EMERGENCE.md §4's two items
("the watcher watched," Phase G turned around) and fixes a stale
internal task-tracker entry (§7 item 7, laws/customs/taboos, was
marked pending despite shipping in v0.87.17).

**Observer attention as a signal into the Town Consciousness**: new
`World.observer_attention` (bounded, `OBSERVER_ATTENTION_MAX_TRACKED
=25`), fed by `POST /observer/attention` — a zero-LLM-cost beacon the
frontend's NPC inspector fires on open, applied through the existing
enqueue-now/apply-next-tick intervention seam.
`SimulationEngine._observer_favorite_agent` resolves the most-
inspected still-living core-cast agent (falling back to most-recently-
inspected). Folded into the monthly consciousness prompt as one plain
fact. Real teeth on the existing intervention menu: the favorite
agent joins `_maybe_schedule_omen`'s existing subject-pick pool
(participates in the same 50%-chance/uniform-pick logic, never a
guaranteed override), and `false_memory`'s core-cast target
preferentially resolves to the favorite when eligible — scoped to two
of the idea's three named examples; dream-symbol/misplaced-object
targeting toward the favorite is a flagged, trivial next increment via
the same helper. Privacy: entirely local, stays in the world's own
save file.

**The consciousness keeps a grudge ledger about interventions**: new
`World.consciousness_grudge_ledger` (-1..1, distinct from `Settlement.
player_standing`), nudged by `_nudge_consciousness_grudge` on every
genuine player `/intervene/*` call — warm if the settlement was
visibly struggling at that moment (`_intervention_hardship_context`:
meaningfully hungry population, or a death/illness/disaster event this
tick), cold by a smaller delta otherwise (asymmetric — help registers
more than mere intrusion, same "easier to lose than earn" shape
`Agent.trust` already uses). Folded into the monthly consciousness
prompt as one private banded line; the model's own free choice of
intervention/tone then organically reflects it.

Verified: direct production-path tests against real `_apply_
intervention` calls (attention counter increments, bounded eviction,
favorite-agent core-cast-only resolution, round-trip + legacy-snapshot
defaults, grudge-ledger warm/cold nudging under forced hardship/calm
context); a real `_maybe_schedule_consciousness` call (fake LLM
client) confirms both new lines reach an actual built prompt.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
— no native module touched. A 20,000-tick organic engine soak (LLM
disabled), exercising a real `observer_attention` intervention
mid-run, completes with zero crashes.

## Current state (v0.87.20)

Direct follow-up per explicit user request ("Complete the item 3 of
ideas.md") — closes docs/IDEAS-2026-07-EMERGENCE.md §3's four items
("closing meaning loops"), all previously unchecked.

**Self-fulfilling prophecy** (`llm/omens.py`, `Settlement.prophecy`):
rides the existing monthly omen call rather than adding a new one —
`PROPHECY_CHANCE` (0.15, on top of the omen's own rarity) invites a
vague forward-looking line + ominous/hopeful tone. While pending
(`PROPHECY_RESOLUTION_WINDOW_TICKS`), folds into `cognition`/
`town_brain` prompts as one more optional grounding line. Resolution
(`SimulationEngine._resolve_prophecies`, new zero-cost tick job) is
deterministic — tallies `World.last_life_events` hardship/prosperity
categories during the window and judges confirmed/forgotten from
whichever led — a documented scope trim versus the idea's "the
beliefs job later judges it" framing, since a second LLM call to
judge fulfillment would double the feature's cost for a question the
settlement's own event record already answers. Nothing in the engine
ever makes a prophecy true; if the village reads it and acts, that's
the villagers' own doing, per Phase G's ambiguity discipline.

**The observer enters the theology** (`Settlement.last_intervention_
tick`): zero new LLM call volume. A genuine player `/intervene/*` call
(never a consciousness-authored one) timestamps the settlement;
`llm/beliefs.py`'s existing monthly job gets one conditional grounding
sentence inviting an optional theory naming a nameless "Quiet
Neighbor," worded to stay superstition-or-coincidence ambiguous —
reuses the entire `Settlement.beliefs`/institution-mirroring pipeline
unchanged.

**Ask the Chronicler** (new `llm/chronicler.py`, `POST /ask-chronicler`
/ `GET /chronicler`): on-demand, mirrors `POST /summary/request`'s
enqueue-now/apply-next-tick seam. Answers strictly from folklore/
chronicle/beliefs/records — never ground-truth stat dicts — so the
chronicler can be honestly wrong. New "📖 chronicler" sidebar panel.

**Subjective map mode**: pure client-side toggle ("👁 subjective"),
zero backend changes — swaps the raw stat grid for a "the village's
own view" panel and switches hover tooltips to plain-language
condition bands/folk place-names.

Verified: direct production-path tests (Settlement field round-trip +
legacy-snapshot defaults; `parse_prophecy` validation; a real
`_maybe_schedule_omen` call via fake LLM client confirming prophecy
formation and no double-formation while one is pending;
`_resolve_prophecies` confirmed/forgotten/no-signal cases driven by
real `last_life_events`; a real `_maybe_schedule_beliefs` call
confirming the Quiet-Neighbor line reaches an actual built prompt only
inside the intervention window; a real `_apply_intervention({"type":
"ask_chronicler", ...})` call driving the actual scheduling pipeline
end-to-end). `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical — no native module touched. A 20,000-tick organic
engine soak (LLM disabled) completes with zero crashes.

## Current state (v0.87.19)

Direct follow-up per explicit user request ("finish 2 of ideas.md") —
closes docs/IDEAS-2026-07-EMERGENCE.md §2's four items (all previously
unchecked); also fixed a leftover duplicate line in §1 from the prior
edit.

**Letters carried by caravans** (`llm/letters.py`, `Settlement.
pending_letters`): monthly, core-cast-only, bonded cross-settlement
pairs only. A real multi-day travel delay (`LETTER_TRAVEL_TICKS`)
before `SimulationEngine._deliver_letters` (day_end) resolves it — a
memory (+ maybe a rumor) if the recipient survived the wait, or a
`letter_arrived_too_late` event if they didn't. Latency is the
feature, not a dropped edge case.

**Settlement-level stance**: closed the two feed/lever gaps on top of
the pre-existing `Settlement.relations`/diplomacy mechanism —
`caravan_relation_factor` (warm regional relations draw more outside
trade) and a migration-triggered relation nudge (`RELATION_MIGRATION_
NUDGE`, the "migrant treatment" signal). "Disaster aid" flagged as
deferred (no aid-transfer mechanic exists yet).

**Refugees after disasters**: extends `_maybe_migrate` (v0.87.18) with
a `Population._housing_pressure` push condition — a disaster ruining
huts drops housing capacity directly, no separate disaster-detection
needed; overcrowded individuals push toward the best-housed named
alternative via the same physically-walking migration mechanism.

**Dialect drift**: rides `narrative_direction`'s existing quarterly
call for zero added LLM volume (`coined_term`/`coined_meaning`
optional fields) — `Settlement.lexicon` feeds back into dialogue as a
light steering line, so settlements slowly stop sounding alike.

Verified: direct tests for the housing-pressure refugee push and the
full letters lifecycle (queue → deliver → both the alive and died-in-
transit branches) against real production code paths. `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical; a
20,000-tick organic soak completes with zero crashes.

**Deviance/justice loop completion**: theft (v0.87.17) now plants a
real `Agent.secrets` entry on the thief and, if a third colocated
agent witnesses it, a rumor-flavored memory on the witness. Dispute
outcomes gained a fourth option, **ostracism** (`llm/dispute.py`, only
offered where a council exists, reserved for a genuinely severe case)
— applies `Agent.standing_penalty` (0..1), which gates SOCIALIZE
targeting and council candidacy while it stands, decaying monthly.

**Migration by choice** (`Population._maybe_migrate`): individuals
could previously only relocate as part of a whole fission party. A
rare, deterministic per-agent push/pull check (bonded partner
elsewhere, ostracism, family feud pressure, starvation next to a
better-fed sister settlement) reuses `depart_for_fission`'s exact
shape at individual scale — settlement_id reassigned immediately,
`travel_target` set for the physical walk — so a migrant carries their
memories/beliefs/secrets for free, the real information vector between
settlements the idea named. `standing_penalty` resets on arrival.

New UI: "Standing" NPC-inspector section (shown only while ostracized);
`migrant_departed` event icon (🎒).

Verified: direct production-path tests for every new mechanic (theft
secret/witness completion, ostracism's standing_penalty/relationship
effects, council-key exclusion, monthly decay, SOCIALIZE's ostracized_
ids exclusion on both native and fallback paths, all three migration
push/pull conditions); a real end-to-end engine test confirms a forced
ostracism dispute reaches the actual scheduling pipeline. `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical; a 60,000-
tick organic soak completes with zero crashes.

## Current state (v0.87.17)

Direct follow-up per explicit user request ("complete my items 8 and 9
first") — closes the two items deferred by the user's own sequencing
choice at the end of v0.87.16 (broad deterministic-sim expansion +
periodic LLM nudges for non-core agents), scoped to four coherent
pieces rather than the full named laundry list (economy/inheritance/
trade/disease/migration/tech were already substantially built; crime,
diplomacy narration, and codified norms were the genuine gaps).

**Crime & theft** (`Population._maybe_commit_theft`): deterministic,
zero LLM cost — a desperate (`THEFT_HUNGER_THRESHOLD`), distrustful
colocated agent may take a fraction of another's personal food stock.
Consequences land asymmetrically on the victim's trust/relationship
read of the thief. `Settlement.thefts_committed` counter + `law_
signal_counts["theft"]` accumulator feed the laws job below.

**Inter-settlement diplomacy** (`llm/diplomacy.py`): the underlying
affinity (`Settlement.relations`) has been deterministic since v0.67.0
but was never LLM-narrated or shown in the main UI — this adds an
occasional named moment (envoy/trade pact/border dispute) on top,
round-robin over settlement pairs, genuine no-op fallback, correctly
inert with fewer than two named settlements.

**Laws, customs, taboos** (`llm/laws.py`, `Settlement.laws`) — closes
§7's last open item, folded together with item 8 since both wanted the
same "codify real lived history" mechanic. Gated on `law_signal_
counts`/`pattern_signal_counts` crossing a threshold (theft or
dispute-feud recurrence), same "spend the call only once texture
exists" discipline as `_maybe_schedule_religion`. Real mechanical
bite: a norm against feuding pushes `dispute.py` toward resolution; a
norm against theft sharpens `_maybe_commit_theft`'s trust penalty
(`THEFT_LAW_PENALTY_MULT`).

**Occasional non-core-cast LLM nudges** (`llm/noncore_nudge.py`) — the
user's own framing, "not fully LLM authored but partially and
occasionally." Exactly one call a month for the entire world
(round-robin, one random non-core agent), never per-agent-scaled;
nudges one trait by a small bounded amount and plants one reflective
memory on a genuine answer, real no-op fallback otherwise.

New monthly job slots: diplomacy=2, laws=5, noncore_nudge=9 (all three
in `MONTHLY_JOBS_WITH_RETRY`). New UI: "Laws & customs" panel, "Crime
& justice"/"Diplomacy" stat tiles, three new event icons.

Verified: direct tests for the theft mechanic and all three new LLM
job parse functions; real end-to-end engine tests (fake `generate_
json` through the actual `CognitionRunner`) confirming all three new
jobs fire through the real scheduling pipeline and mutate settlement/
agent state correctly — not a reimplementation. `scripts/verify_
native_soak.py` (2 seeds x 800 ticks) byte-identical.

## Current state (v0.87.16)

"Cognition-quality cluster" per explicit user direction, responding to
a live report that the cultural simulation converges too strongly on
one dominant narrative and a narrow topic set. Items 8 (broad
deterministic-sim expansion) and 9 (periodic LLM nudges for non-core
agents) explicitly deferred to a follow-up per user sequencing choice.

**Occupation + personality-consistent interpretation**: `Simulation
Engine._occupation_for` reads dominant skill as a trade label (farmer/
builder/healer); `PERSONAL_SYSTEM_PROMPT` now instructs the model to
let occupation/temperament color interpretation and stay consistent
with who the agent already is — previously this job never received
trait grounding at all, unlike cognition/dialogue.

**Support multiple competing beliefs**: `find_belief_index_by_subject`
gained `max_competing` — a same-subject `revises: null` answer no
longer force-merges unconditionally; up to `MAX_COMPETING_BELIEFS_
PER_SUBJECT=2` distinct theories about one subject may now coexist.
Both belief system prompts explicitly invite a genuine second theory
when interpretations would honestly differ.

**Reduce conversational convergence**: dialogue's weather clause is
now conditional on `weather_notable` (a real storm/rain/snow, not
routine clear/partly-cloudy/overcast) instead of unconditional in
every exchange; the system prompt explicitly broadens allowed subject
matter and de-prioritizes weather as filler.

**Improve memory weighting**: `_remember` dampens near-duplicate
memories (`MEMORY_REPETITION_DAMPING`); `decay_memory_salience` uses a
permanently slower rate for any causally-tagged (`memory_causes`)
memory rather than a current-salience threshold check (which measured
to still converge to the same floor within a year regardless of
starting significance — rejected in favor of the tag-based check).

**Historical identity**: new `Agent.core_memories` (cap 5) — a memory
evicted from the ordinary 8-slot window graduates here when causally-
tagged or highly salient, consumed in cognition (keyword-matched) and
personal-belief prompts (given in full). New "Never forgotten" NPC-
inspector section.

Deliberately deferred, flagged not dropped: caravan/migrant-introduced
competing ideas, generational drift in tradition interpretation.

Verified: direct production-path tests for every piece (occupation
labeling, competing-theory cap behavior, weather-notable gating,
repetition dampening, because-tagged decay measured over a simulated
year, core-memory graduation on forced eviction, round-trip + legacy-
snapshot defaults). `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical — no native module touched.

## Current state (v0.87.15)

Closes three more §7 items (bounded episodic planning, emergent
leadership, knowledge lifecycle) plus a direct user-directed survival-
decision framing change. §7's last item (laws/customs/taboos)
explicitly deferred.

**Survival-decision framing**: past `cognition.SURVIVAL_HUNGER_
THRESHOLD`/`SURVIVAL_ENERGY_THRESHOLD` (0.6/0.3), `build_prompt` stops
posing goal-setting as an open question — "your current priority is
obtaining food/resting — explain how you go about it," narrowing the
LLM's contribution to the reason, not the choice, once physical need
has already decided it.

**`Agent.plan`**: multi-day intent authored by Reflect() (zero added
calls), ticked down daily by `Population.tick_plans`, consumed as a
cognition-prompt line and a `fallback_goal` keyword bias.

**Emergent leadership**: council seat selection ranks by `_prominence`
(age tiebreak only); a throttled contest check lets a standout non-
member displace the weakest sitting member (`council_seat_contested`).
`Population.council_faction_majority` biases dispute/town_brain
framing when one FACTION holds a council majority.

**Knowledge lifecycle**: `Settlement.invention_knowledge` tracks
knowers for the most recent 20 inventions — spreads via the existing
skill-teaching colocation loop, goes dormant when the last knower dies
(`knowledge_lost` event), may be rediscovered by an heir
(`INVENTION_REDISCOVERY_CHANCE`). UI marks dormant entries "💤".

Verified: direct production-path tests for all four pieces (prompt
framing at/below thresholds, plan lifecycle, a real council contest via
`_maybe_refresh_council`, `council_faction_majority` reaching both
dispute/town_brain prompts, a 60-trial death/dormancy/rediscovery rng
sweep, diffusion via a real `_maybe_teach_skills` call); round-trip +
legacy-snapshot defaults for `Agent.plan`/`Settlement.invention_
knowledge`. `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical — no native module touched.

## Current state (v0.87.14)

Implements docs/IDEAS-2026-07-EMERGENCE.md §7 items 1-2 ("adaptive
retrieval layer" + "causal memory links"), explicit user direction.

**Causal memory links**: new `Agent.memory_causes`, index-aligned with
`memories`/`memory_salience` (same pad/truncate legacy-snapshot
discipline). `Population._remember` gained an optional `because: str`,
wired at every call site where the engine objectively knows the cause:
death/inheritance grief (`because=f"{name} died"`) and all three
dispute outcomes (`because=f"dispute with {them.name}"`). Deliberately
NOT implemented this pass: Reflect() authoring *subjective* — possibly
wrong — causal links ("the omen, then the flood") — flagged as the
natural next increment, not silently dropped.

**Adaptive retrieval layer**: new `retrieve_relevant_memories`
(`hearthmind/agents/agent.py`) scores every stored memory by recency,
salience, keyword-overlap relevance to the agent's current situation,
and a small bonus for a known causal link — replaces `cognition.
build_prompt`'s previously-fixed `memories[-3:]` slice with the SAME
prompt-slot budget (`RECENT_MEMORIES_IN_PROMPT=3`), so a ten-year-old
high-salience memory can now outrank a mundane recent one when it's
actually relevant, with prompt size unchanged. `_overlap_tokens`
(previously local to `simulation/engine.py`'s `_matching_lesson`
fallback) moved to `agent.py` so the new function can share it without
an engine->agent import inversion; `engine.py` now imports it instead
of redefining it. Scoped to `cognition.build_prompt`'s memory
selection only — `dialogue.py`/`beliefs.py`'s own fixed slices and
non-memory stores (folklore/lessons) untouched this pass. A
`because`-tagged memory shown in a prompt gets a "(because: ...)"
suffix.

New `retrieval_diagnostics()` (the idea doc's own explicit ask —
"measured, not assumed") tracks call count and how often the scored
top-k diverged from a plain recency slice, surfaced at `/diagnostics.
memory_retrieval` (dev-console JSON dump only, same reachability as
`llm_prompt_stats`).

Verified: direct tests confirm relevance surfaces an older
high-salience memory over a merely-recent one; round-trip + legacy-
snapshot defaults for `memory_causes`; a real `Population._remember`
eviction test confirms all three parallel lists (`memories`/
`memory_salience`/`memory_causes`) stay aligned; a real
`Population.apply_dispute` call confirms feud/reconcile outcomes tag
`because` correctly; a real built `cognition.build_prompt` call
confirms a `because` tag reaches the actual prompt text.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
this batch touches no native module.

## Current state (v0.85.4)

Direct follow-up to v0.85.3, per explicit request to intelligently
summarize rather than blindly slice: "instead of just slicing the
prompts can we intelligently summarise it, without losing much of the
context?" A recency slice (`PROMPT_BELIEFS_MAX`) bounds tokens but
silently drops whatever falls out of the window — a real theory the
village holds, just an older one, loses all representation.

New `Settlement.belief_digest`: one LLM-authored sentence condensing
the *entire* current belief set's overall shape, written by extending
the existing monthly belief-forming/revising job with one extra field
— zero added call volume, same discipline `Agent.semantic_memories`/
`mind` already established for "distill instead of adding a call."
`llm.beliefs.parse_digest` only overwrites the stored digest on a
genuine LLM answer, retained (never fabricated) across a fallback
stretch — same `player_influence`/`omen_seed`/`dream_seed` discipline.
`chronicle`/`town_brain` now lead with the digest for overall shape,
plus a much smaller raw-belief slice (`PROMPT_SETTLEMENT_BELIEFS_
MAX=2`, down from 5) for concrete grounding — digest-plus-specifics,
the same split `Agent.semantic_memories` has alongside raw `Agent.
memories`. `town_brain`'s `council_beliefs` (no digest mechanism yet,
a narrower per-institution list) keeps the plain 5-item slice.

Verified: `parse_digest` validation; a real end-to-end engine test
confirms the digest reaches captured chronicle/town_brain prompts; a
forced fallback-only stretch after one real success leaves a
previously-set digest exactly unchanged; round-trip + legacy-snapshot-
defaults-cleanly tests; a 5-seed x 15,000-tick soak (LLM disabled, this
change is LLM-path-only) confirms no regression.

## Current state (v0.85.3)

Direct audit for an explicit request: "check for prompt growth over
multiple in-game decades, we should summarise large prompts and keep
them bounded." A real multi-decade run isn't practical to wait out
(96 ticks/day; even 200k ticks is only ~5.7 years) — instead measured
every settlement-scoped/per-agent `build_prompt` function against a
*synthetically saturated* Settlement/Agent (every capped list filled to
its ceiling), the steady-state plateau any long-running world
eventually reaches and stays at.

**Confirmed**: every collection this project's prior memory-leak audits
capped in storage (traditions/inventions/festivals/folklore/rituals/
beliefs/records/narrative_themes, per-agent memories/semantic
memories/secrets) is genuinely bounded, and most prompts already slice
further down on top of the storage cap (`PROMPT_CULTURE_LIST_MAX=5`,
various internal `[-N:]` slices). `place_names` has no explicit cap but
is naturally self-limiting by map geography (one river + one per lake).

**Found two real gaps**: `chronicle.py`/`town_brain.py` both received
the *entire* capped `Settlement.beliefs` list unsliced (`town_brain`
sends TWO such lists). At full saturation this measured ~1291/~1442
tokens — over half of `Config.llm_num_ctx=2560` on the prompt alone,
before the system prompt or the reserved `llm_num_predict=448` — a
real plateau any sufficiently long-running world reaches, not a
hypothetical. Fixed via new `SimulationEngine.PROMPT_BELIEFS_MAX=5`
(same "bound the prompt, not the store" shape as `PROMPT_CULTURE_
LIST_MAX`), applied at all five belief-into-prompt call sites.
`llm/beliefs.py`'s own belief-revision prompt was deliberately left
unsliced — it genuinely needs the full current belief set to correctly
merge/revise without duplicating an entry, and measured under budget
(~1118 tokens) even unsliced.

Verified: re-measured every prompt post-fix (chronicle ~1158 tokens,
town_brain ~1176, both from ~1291/~1442); a direct end-to-end engine
test (fake LLM client, settlement beliefs forced to the full cap with
uniquely-markered text) confirms the real production code path sends
exactly 5 beliefs to both a captured chronicle prompt and a captured
town_brain prompt.

## Current state (v0.85.2)

Direct fix for a live report: "NPCs actually repair/maintain
buildings... Looks like they aren't." Root cause: the deterministic
side was already correct (`_dispatch_movement`'s WANDER branch biases
toward `damaged_building_positions` via `work_positions`, and
`_maybe_repair` applies real condition restoration once an awake agent
is colocated), but a live LLM choosing goals (the project default)
never got told a building needed repair or that `'wander'` was the way
to help — the model had no basis to rationally pick it over forage/
socialize/gather, so repair was left to chance colocation.
`llm/cognition.py`'s `SYSTEM_PROMPT` now explains `'wander'` can mean
going to help repair; `build_prompt` gained `needs_repair: bool`
(computed via `Population.damaged_building_positions(home)` in
`SimulationEngine._schedule_due_cognition`), adding one grounding
sentence when true — same "ground the choice in what's reachable"
treatment `nearest_food_steps` already gets. Roads are unaffected
(self-maintaining via foot traffic, no agent decision); the
deterministic fallback path was already correct and untouched.
Verified via prompt-construction tests and a real end-to-end engine
test (fake LLM client, forced damaged building, forced significance
gate) confirming an actual cognition prompt includes the repair
sentence.

## Current state (v0.85.1)

Direct fix for a live 60,000-tick report: `population_total: 0` with
no path back — v0.85.0's below-core-cast migrant trickle had
explicitly excluded `count == 0`, per the project's own prior standing
rule that true extinction is a legitimate, permanent ending. The user
asked for this fixed, which is a direct, explicit reversal of that
rule (see "Diagnostic history index" below), not a bug fix within it.

`Population._maybe_welcome_migrant` now fires at 0 population too
(same chance formula as the near-extinction band, openness term
skipped to avoid dividing by zero with no survivors). The live
diagnostic's settlement had also lost every building
(`building_completed`/`building_ruined`/`building_reclaimed` all equal
at 3 — full decay-and-reclaim cycle with nobody left to repair
anything), so there was no building or survivor position left to
anchor a migrant's arrival on. New `Population._center_walkable_tile`
scans outward from the map's geometric center for the nearest walkable
tile as a neutral fallback anchor — `terrain` (already available in
`Population.tick()`) threads through to `_maybe_welcome_migrant` for
this. Verified via a real end-to-end `World.tick()` test that
force-wipes population and buildings to reproduce the live scenario
exactly, plus direct unit tests for the walkable-tile scan's edge
cases (water at map center, fully unwalkable map) and a 5-seed
engine soak with two forced mid-run extinctions.

## Current state (v0.87.13)

Direct fix for a live report: "everything wears down too quickly."
Root cause: building/vehicle decay used one binary "harsh weather"
gate (any of precipitation/wind/snow past a threshold) flipping a flat
3.0x/2.0x multiplier — measured against the real weather distribution,
this fired often enough that the effective average decay was much
faster than the base rate suggested, with zero differentiation between
kinds of bad weather.

Halved the baseline rates (`buildings.DECAY_PER_TICK_BASE` 0.0004 ->
0.00022, `vehicles.VEHICLE_DECAY_PER_TICK_BASE` 0.0003 -> 0.00016; C3's
"decay is never zero" principle preserved). Replaced the binary gate
with `buildings._weather_decay_catalyst`: four continuously-scaled,
additive catalysts — damp/rot, dry-heat/cracking, frost/freeze-thaw,
wind/structural — each contributing its own share rather than one flat
switch, so a single bad reading is a mild bump while a genuinely
miserable compound day (cold+wet+windy) stacks several real effects.
Vehicles read the same catalyst at 2/3 strength (preserving the old
2.0-vs-3.0 building/vehicle ratio). `SEASON_DECAY_MULTIPLIER`'s range
narrowed ({1.4,1.15,1.0,0.85} -> {1.15,1.05,1.0,0.95}) since winter's
freeze-thaw/damp is now captured directly by the per-tick catalysts
rather than a coarse seasonal average. Measured effective average
full-decay time: ~3059 ticks (30k-tick realistic sample), up from the
old worst-case baseline. Entirely Python-side — native fast paths take
precomputed scalars, no C++ changes needed.

Verified: direct tests for catalyst monotonicity/ordering/compounding,
a real `Settlement.tick` integration test confirming buildings decay
faster than vehicles under identical weather and both decay faster in
a winter storm than clear summer weather. Re-verified against the
rebuilt native extension; native soak confirms native/Python paths
match exactly at the new rates.

## Current state (v0.87.12)

Two independent pieces per explicit user direction ("try closing
point 7 first" = docs/IDEAS-2026-07-EMERGENCE.md §7's 9 items;
"reduce the amount of rain, there is no variety").

**Weather retune**: measured realized sky-band distribution directly
(100k ticks, default seed) — old cutoffs were balanced (~48%/47%
dry/rain) but only 4 labels, "raining" read as a coin flip. Split into
6 bands (`clear`/`partly_cloudy`/`overcast`/`drizzle`/`light_rain`/
`heavy_rain`, new `WeatherState.sky()` accessor) retuned against finer
percentiles — real rain now ~22% of ticks (down from ~47%), dry ~74%,
snow unchanged ~4%. Frontend `RAIN_FLOOR` moved to match the new
drizzle onset (0.45). Zero effect on persisted state (`describe()`/
`sky()` are derived-only; `compute_weather`'s blend math untouched).

**§7 items 5/8/9 of 9** (see docs/IDEAS-2026-07-EMERGENCE.md for full
status of all 9 — items 1/2/3/4/6/7 remain unimplemented):
- **Per-agent voice**: `Agent.voice`, authored at the existing
  genesis `mind` call (zero added LLM volume, `llm/mind.py` schema
  widened), consumed in dialogue prompts.
- **Institution objectives**: `Institution.objective`, authored by the
  existing monthly institution-belief job, consumed in cognition
  prompts via `Population.institution_objective_for` — not yet wired
  into dispute framing.
- **Dialogue novelty memory**: `Population.dialogue_topics` per-pair
  ring (cap 3), fed from a new `topic` field in the dialogue LLM
  schema (never fabricated for the fallback), read back as a "find
  something new" steering line on the pair's next exchange.

Verified: direct tests against real production paths for all three
(genesis call, institution-belief job, dialogue schedule/apply cycle
— fake LLM clients through the actual engine methods); round-trip +
legacy-snapshot defaults; weather-distribution measurement confirming
all six bands fire with the intended rain-share reduction. Re-verified
against the rebuilt native extension; native soak byte-identical.

## Current state (v0.87.11)

Continued docs/IDEAS-2026-07-EMERGENCE.md §1 backlog ("generational
feuds between FAMILY institutions"). Promotes a repeated pattern of
pair-level `dispute` `outcome == "feud"` results between two different
FAMILY institutions' members into a durable, symmetric `Institution.
feuds` entry (`FAMILY_FEUD_PROMOTION_THRESHOLD=3`, working counter on
`Settlement.family_feud_counts`, same accumulate/threshold/consume-
and-reset shape as `ritual_signal_counts`) — event-driven from `_maybe_
schedule_dispute`'s apply(), not a per-tick scan. New `Population.
family_of`/`families_feuding` helpers (mirror `faction_of`).
Inheritance is free: `Institution.member_agent_ids` already outlives
individual members, so a feud covers descendants with no new
mechanism.

**Real consequences, existing mechanics only**: `llm/dispute.py`
gained `rival_families` (mirrors `rival_factions`) biasing both the
prompt and deterministic fallback toward a harder-to-reconcile
outcome. `Population._maybe_reproduce`'s affinity gate demands
`REPRODUCTION_AFFINITY_THRESHOLD + FAMILY_FEUD_AFFINITY_PENALTY` (not
a hard block) for a cross-feud-line pair — the emergent "Romeo and
Juliet" the idea doc names, falling out of existing affinity mechanics
colliding with the feud gate. New `family_feud` event (⚔️, "people"
filter group) — zero new UI code otherwise.

Verified: direct tests for the promotion mechanism (threshold,
symmetry, no-double-promotion), round-trip + legacy-snapshot defaults,
dispute framing wiring, and the affinity gate (ordinary threshold
rejected across a feud line, stronger bond overcomes it, non-feuding
control unaffected). A real end-to-end test drives the actual
`_maybe_schedule_dispute` path (fake LLM client) across the threshold
and confirms the symmetric feud forms through genuine scheduling.
Re-verified against the rebuilt native extension; native soak
byte-identical.

## Current state (v0.87.10)

Two independent pieces per explicit user direction ("keep checking off
incomplete things from the list. Try to minimize dropping completed
LLM calls... instead make each LLM call count").

**Season/year LLM job retry window**: `tradition`/`religion`/
`narrative_direction`/`culture_digest` (season_end) and `documentary`
(year_end) were still single-exact-tick gated, unlike the monthly jobs
(`MONTHLY_JOBS_WITH_RETRY`, v0.81.1) — a backpressured boundary tick
meant a full season/year of silent loss. New `SEASON_YEAR_JOBS_WITH_
RETRY`/`SEASON_YEAR_JOB_RETRY_WINDOW_DAYS=5` + `SimulationEngine.
_season_year_gate`/`_mark_season_year_resolved` mirror the monthly
mechanism. `invention` deliberately excluded — it rolls its own
per-tick RNG chance after the boundary gate (`INVENTION_CHANCE_PER_
SEASON`), and widening its window would re-roll that chance across
multiple days, inflating the tuned probability (same reason festival/
caravan/omen stay excluded from the monthly version).

**Wedding ceremonies** (docs/IDEAS-2026-07-EMERGENCE.md §1, the
deferred half of v0.87.9's funerals item). Trigger: `_extend_family`
already returns a `family_formed` event only the FIRST time two
parents have a child together — exactly the once-per-couple "just
bonded" signal a wedding needs, no new tracking required.
`Population._maybe_reproduce` sets new `Agent.wedding_target`/
`wedding_ticks_remaining` (`WEDDING_DURATION_TICKS=48`, half `MOURNING_
DURATION_TICKS`) on the couple plus kin/bonded guests, anchored at the
birth tile. `_dispatch_movement` gained a wedding override mirroring
mourning's exactly (checked just after it); `Population._tick_
weddings` (new) expires the gathering and bumps every guest's joy
(`WEDDING_JOY_BUMP=0.25`). Zero LLM cost, zero new UI code — same
"visible through existing map/agent rendering" shape as funerals;
`family_formed` already has a main-feed icon.

Verified: direct tests for both pieces against real production paths
(gate open/close/expire/reopen; a real backpressure-forced-then-
retried religion job; wedding invite/movement/hold/expiry/no-re-
trigger-on-second-child). A real 30,000-tick organic engine run (LLM
disabled) produced 845 ticks of active wedding gatherings with zero
test-side scripting. Re-verified against the rebuilt native extension;
`scripts/verify_native_soak.py` (3 seeds x 2000 ticks) byte-identical.

## Current state (v0.87.9)

Continued §1 backlog implementation per explicit user direction
("continue... from vision," gemma-4-e4b dropped). Third §1 item:
"ceremonies agents attend" — funerals only (weddings need a real
"couple formed" trigger this codebase doesn't have yet, flagged not
faked).

`Population._apply_deaths`'s existing kin/bonded grief loop now also
sets `Agent.mourning_target` (the grave position, same tile `add_
memorial` records) and `mourning_ticks_remaining` (`MOURNING_DURATION_
TICKS=96`, ~a day). `_dispatch_movement` biases mourners toward the
grave and HOLDS them there (unlike `travel_target`, doesn't clear on
arrival — a gathering, not an errand) until `Population._tick_mourning`
(new, same tick-down-to-revert shape as `sick_ticks`/`immune_ticks`)
expires it, easing (never erasing) grief by `MOURNING_GRIEF_EASE=0.15`.
Zero LLM cost, zero new UI code — mourners converging on a grave marker
is visible through existing map/agent rendering alone.

Verified: direct tests against real `_apply_deaths`/`_dispatch_
movement`/`_tick_mourning`; a real 30,000-tick run organically produced
13 deaths / 1,204 ticks with active mourning, no test scripting.
Native soak byte-identical, re-verified against the rebuilt extension.

## Current state (v0.87.8)

Continued backlog implementation per explicit user direction (LLM cost
no longer a hard constraint), plus a real C++ build fix and a blocked
gemma-4-e4b diagnosis.

**C++ build parallelism, root cause found**: v0.85.6/v0.87.3 tuned
`build_ext`'s `--parallel`, which only parallelizes across multiple
`Extension` objects (verified directly against setuptools._distutils
source) — this project has exactly ONE `Pybind11Extension`
(~21 files), so that lever could never have done anything. `setup.py`
now installs pybind11's `ParallelCompile` (the documented fix for this
exact shape of project), which thread-pools over individual source
files within one extension. Verified live: 5 concurrent `cc1plus`
during a clean build (was 1), soak byte-identical.

**SEEK_PERSON directed intent** (docs/IDEAS-2026-07-EMERGENCE.md §1's
top item): new `AgentGoal.SEEK_PERSON` pathfinds to a SPECIFIC agent
(`Agent.seek_target_id`) rather than SOCIALIZE's nearest-anyone.
`Population._seek_person_candidate` deterministically picks one
candidate+intent from existing trust/secrets/emotion state — console
(bonded + grieving), confront (secret + distrust), confide (most
trusted). Core-cast-only (LLM cognition offers it; deterministic
fallback never does), so volume stays bounded automatically. Arrival
rides the EXISTING colocated-dialogue mechanism with zero new
scheduling logic — the intent reaches dialogue for free via
`goal_reason`. UI surfacing is free (goal/goal_reason already render
generically). Not implemented: "apologize" (needs per-pair dispute
history this codebase doesn't track).

**gemma-4-e4b**: blocked on the user providing the actual llama-server
startup error/log — confirmed a startup failure, not a hearthmind-side
bug, but nothing here hardcodes model-specific handling so a real fix
needs the real error text.

Verified: direct tests for candidate priority, round-trip, prompt
grounding, apply_goal set/clear, movement+arrival; full end-to-end
engine test with a fake LLM client confirms the real scheduling ->
apply pipeline. Re-verified against the rebuilt native extension.
Native soak (3 seeds x 2000 ticks) byte-identical.

## Current state (v0.87.7)

Direct follow-up to v0.87.6, per explicit user request to start
implementing docs/IDEAS-2026-07-EMERGENCE.md. Picked the two highest-
leverage, zero-LLM-cost items from §1.

**Heritable temperament with mutation**: `Population._inherited_
traits(a, b, rng)` blends both parents' trait values (average) plus
Gaussian mutation (`Agent.TRAIT_INHERITANCE_MUTATION_STDDEV=0.15`),
clamped -1..1, wired into `_maybe_reproduce`'s newborn `Agent(...)`
call. Correction to the item's own premise: traits were never actually
rolled at spawn (every agent starts neutral, 0.0 on all four axes) —
the real gap was newborns having zero inherited variance at all, now
fixed.

**Deathbed release of secrets**: `Population._apply_inheritance` (H7's
existing heir-resolution job) may now also pass the deceased's
freshest secret to the same heir goods/skill/bias already transfer to
(`DEATHBED_SECRET_HEIR_CHANCE=0.3`), attributed to the deathbed; a
further chance (`DEATHBED_SECRET_RUMOR_CHANCE=0.4`) it leaks as a
vague rumor via `Population.spread_rumor` (never the secret's actual
contents). Secrets now have the full lifecycle the audit doc named:
planted -> guarded -> leaked at death -> distorted by
InterpretRumor() -> maybe folklore.

Verified: direct tests against real production paths (`_inherited_
traits` mean/clamp over 2000 samples, a real in-engine birth
inheriting a high-resilience tendency, a 400-trial `_apply_
inheritance` test landing at the expected ~0.3 transfer rate).
`scripts/verify_native_soak.py` byte-identical — no native module
touched, no new persisted fields, no snapshot migration needed.

## Current state (v0.87.6)

Direct follow-up to v0.87.5, per explicit user request: implement its
own flagged-but-deferred next step, file an externally-submitted
emergence-ideas audit as tracked backlog, and act on a follow-up
directive to upscale LLM utilization now that swap pressure is
reportedly resolved.

`scripts/run.sh`'s new `LLAMA_METRICS_ENDPOINT` (default on) passes
`--metrics` to llama-server; `llm.client.fetch_llama_server_metrics()`
polls its Prometheus `/metrics` endpoint (KV-cache occupancy, queue
depth, throughput — no prompt content, deliberately not `/slots`).
`SimulationEngine` polls it every `LLAMA_METRICS_POLL_SECONDS=30` as a
real-time-gated (not tick-gated — keeps polling through any pause)
background task, surfaced at `/diagnostics.llama_server_metrics`
alongside (not replacing) the char-based `llm_prompt_stats` estimates.

`docs/IDEAS-2026-07-EMERGENCE.md` filed — see "Long-term design
vision" above for the pointer.

**LLM utilization upscale, directed**: user reports `LLAMA_CACHE_
RAM=0` (v0.87.5) resolved the swap/memory pressure that had driven
several prior config pull-backs — its stock 8GB reservation plausibly
explains more of that history than the KV-cache/concurrency sizing
those pull-backs targeted. Raised (each documented in `config.py` as
a directed increase, not a fresh measurement): `llm_max_concurrent`
2->3, `llm_num_ctx` 2560->3072, `llm_num_predict` 448->512,
`llm_core_cast_size` 14->18 (restoring the v0.72.3 value),
`llm_max_calls_per_day` 320->480. `scripts/run.sh`'s `LLAMA_PARALLEL`
(->3)/`LLAMA_CTX_SIZE` (->9216) kept in step. Deliberately a partial
restore, not the full v0.72.3 ctx/predict peaks. Model choice (user
testing q5_k_m `gemma-4-e2b-it`) left untouched pending a live report.
Report back `/diagnostics.system_memory`+`llm_prompt_stats`+`llama_
server_metrics` after adopting this; re-lower all five together if
pressure reappears.

## Current state (v0.87.5)

Explicit user directive: audit `--cache-ram`, and audit every LLM
prompt for token density — retrieval/summaries over raw dumps,
measurement-driven optimization. Full detail in CHANGELOG.md.

**`LLAMA_CACHE_RAM=0` now the default** (`scripts/run.sh`) —
llama-server's host-RAM prompt cache defaults to 8192 MiB (8GB!) if
never passed, sized for a shared-prefix/many-similar-prompts workload
this project doesn't have (every prompt is freshly built per agent/
settlement/tick). Confirmed against upstream docs, not assumed.
Re-enable via a positive MiB value if `/diagnostics.llm_prompt_stats`
ever shows this workload's shape has changed.

**Prompt audit: one real fix, rest re-confirmed tight.** New
`persistence/snapshot.py:_dedupe_rumor_topics` collapses exact-
duplicate rumor-spread events (the same rumor text logged once per
pair that shares it) into one line + an echo count, wired into
`recent_events_diverse` (benefits chronicle/town_brain/beliefs/
documentary/personal_belief at once) — a live-diagnostic example
showed 9 of 40 chronicle event lines were the literal same rumor.
Genuine retellings (`InterpretRumor()`'s deliberate distortion) are
untouched since they don't exact-match. Everywhere else (cognition,
dialogue, personal_belief, town_brain, beliefs, dispute, invention)
re-measured and confirmed already tight from prior audits (v0.85.3-.5,
v0.86.6, v0.87.1) — no further raw-list-to-summary conversion found
with a measurable cost to justify one.

**New telemetry**: `_llm_prompt_stats`/`llm_prompt_stats_summary()`
tracks prompt/completion char-based token estimates and latency BY
JOB NAME (not just the prior aggregate), surfaced at `/diagnostics.
llm_prompt_stats`. Closed a real gap: `cognition` calls weren't
recorded in `last_llm_calls`/stats at all before this. Recommended
next step (not implemented): poll llama-server's own `/slots`/
`/metrics` for real KV-cache/context-utilization/prompt-cache-hit-rate
numbers instead of char-based estimates — flagged as a genuinely new
polling subsystem, out of scope for this pass.

Verified: direct tests for dedup + prompt-stats against the real
`_schedule_llm_job` production path; `scripts/verify_native_soak.py`
(3 seeds x 2000 ticks) byte-identical.

## Current state (v0.87.4)

Explicit user directive: implement all six remaining items on
docs/VISION-2026-07-LEARNING.md's deferred list in one batch. Full
detail in CHANGELOG.md; durable facts only here.

1. **Non-core-cast lessons**: deterministic templates
   (`RECOVERY_LESSON_TEMPLATES`/`RECONCILE_LESSON_TEMPLATES`) fire at
   illness recovery and dispute reconciliation for every agent, zero
   LLM cost — the core-cast-gating rule only applies to LLM-authored
   per-agent decisions.
2. **Keyword-overlap lesson matching**: `_matching_lesson` falls back
   to a stdlib keyword-overlap comparison (`_overlap_tokens`, no
   embeddings) against `working_memory` when no exact situation tag
   matches.
3. **Cross-generational lesson inheritance**: `_apply_inheritance`
   passes the deceased's freshest lesson to the heir
   `INHERITANCE_LESSON_CHANCE=0.5` of the time, attributed, not
   guaranteed.
4. **Continuous memory-salience fade**: `Population.decay_memory_
   salience()` (daily) + `faded_memory_text()` (agent.py) — a memory
   that survives eviction still slowly reads hazier in prompts.
5. **LLM-narrated skill mastery** (new `llm/skill_mastery.py`): the
   one new LLM call this batch adds — core-cast only, replaces the
   just-written deterministic mastery memory in place with a
   reflection grounded in the agent's own recent memories. Non-core
   agents and the settlement event log are untouched.
6. **Consciousness player-theory revision**: new `revises_leading`
   field lets the monthly consciousness job update its leading
   `consciousness_player_model` entry in place (confidence/
   revision_count/revised_tick, the last two previously dead schema
   fields since v0.84.0) instead of always appending an independent
   new theory.

Verified: direct production-code tests for all six; `scripts/verify_
native_soak.py` (3 seeds x 2000 ticks) byte-identical.

## Current state (v0.87.3)

Five items from one user turn (parallel build still not visibly
working, reconsider sim-size defaults for speed/memory, where repair
counters show in the UI, continue deferred item 4 of the "learns like
a human" doc, and make `LLAMA_RESTART_HOURS` restarts pause the sim and
show in the UI/diagnostics). Full detail in CHANGELOG.md; durable facts
only here.

**Parallel build**: `setup.py`'s `BuildExtOptional.finalize_options`
now sizes `--parallel` from `os.sched_getaffinity(0)` (cgroup/taskset-
aware) rather than `os.cpu_count()` (machine-total, ignores affinity
restrictions) — the likely root cause of a live "still not parallel"
report on a constrained host, since the v0.85.6 fix used `cpu_count()`.

**Sim-size defaults: audited, not changed.** A real headless soak
(LLM disabled, default 64x64/pop-12) measured tick cost staying under
1% of the 1000ms tick budget even as population grows toward
`POPULATION_CAP=400` (6.2ms/tick at pop~12, 9.8ms/tick at pop 83,
extrapolates to ~2-3% of budget at the cap). The tick loop is not the
smoothness bottleneck at any current-default population/map size — the
real lever remains LLM call throughput/config (already tuned from live
hardware reports, see "Hardware target" above), not `width`/`height`/
`POPULATION_CAP`/`tick_seconds`. Changing those without a measured
problem would violate this project's own "measure before tuning" rule
— if population/map size are ever raised well past current defaults,
finish R8 (port `Population`'s remaining per-agent tick logic to the
C++ store) first.

**Repairs & upkeep**: already in the main UI as its own stat tile
(v0.86.7) — no gap, just a pointer.

**Town Consciousness trend + theory**: `_player_intervention_trend`
now folds the consciousness's own leading `consciousness_player_model`
belief into the frequency-trend sentence (`_leading_player_theory`,
new helper) instead of the two facts sitting unconnected in the
prompt. Zero added LLM call volume — closes deferred item 4 of
docs/VISION-2026-07-LEARNING.md.

**`LLAMA_RESTART_HOURS` now pauses the simulation, not just the LLM
calls.** New `Config.llm_restart_sentinel_path`: `scripts/run.sh`'s
restart supervisor touches/removes a file around the restart;
`SimulationEngine.llama_server_restarting()` polls it the same way
`llm_pressure_paused()` is polled, and `run_forever` pauses ticking
outright while it's set (same `PAUSED_POLL_SECONDS` cadence as every
other pause reason) instead of leaving every individual LLM call to
fall back/defer independently during the outage. Tracks
`_llama_server_restarts` (edge-counted) and forces an out-of-band
broadcast on the transition so the UI's new "🔁 llama-server
restarting" banner and `/diagnostics.llama_server_restarts_total`/
`llama_server_restarting` update promptly rather than only after
ticking resumes. Zero cost when no sentinel path is configured (the
default — `run.sh` only passes one when `LLAMA_RESTART_HOURS>0`).

## Current state (v0.87.2)

Two independent pieces per explicit user direction: continue item 2
of `docs/VISION-2026-07-LEARNING.md`'s deferred list (deeper
settlement pattern-recognition), and reduce llama-server heap growth
without relying on `LLAMA_RESTART_HOURS`.

`_detect_ritual_signals`'s `pattern_signal_counts` gained
`disease_outbreak` (matched specifically on `_maybe_outbreak`'s
"fallen ill" index-case text, not person-to-person spread) and
`wildlife_recolonization` (the existing `wildlife_recolonized` event
category) alongside the existing `starvation_death`/`dispute_feud`
pair — `_maybe_schedule_beliefs` now has four possible "pattern
noticed" grounding sentences instead of two, zero added call volume.

`scripts/run.sh` gained `LLAMA_MALLOC_ARENA_MAX`/`LLAMA_MALLOC_MMAP_
THRESHOLD_KB`/`LLAMA_MALLOC_TRIM_THRESHOLD_KB` (all default unset) —
glibc malloc tunables exported only into the llama-server child
process via an `env` prefix, a complement to `LLAMA_RESTART_HOURS`
that reduces the RATE heap fragmentation accumulates rather than
periodically reclaiming it. Verified end-to-end against a mock
llama-server that the converted byte values reach only the child
process and the default (unset) path is unchanged.

Verified: direct tests confirm the two new pattern counters increment
correctly (outbreak-origin vs. person-to-person illness correctly
distinguished) and the sentences reach a captured beliefs prompt;
`scripts/verify_native_soak.py` byte-identical.

## Current state (v0.87.1)

Direct follow-up per explicit user direction: highest-priority
deferred item from `docs/VISION-2026-07-LEARNING.md` first (dialogue
consumption of lessons — `dialogue.build_prompt` now reads each
speaker's situation-matched lesson via the same `_current_situation_
tag`/`_matching_lesson` helpers cognition already used, zero added
call volume), plus a fresh RAM-to-disk audit specifically for LLM-
related memory growth. Audit found nothing new to move: `Agent.
lessons`/`Settlement.pattern_signal_counts` are tiny fixed caps that
exist to be read on every relevant prompt build (moving to disk-on-
demand would add a SQLite round-trip to the hottest per-tick code
paths for no real RAM benefit), and `Settlement.records`/`memorials`
were confirmed to already have durable backing beyond their caps
(`record_written`/`death` events) — the one genuinely un-backed detail
(exact memorial grave-marker position past `MEMORIALS_MAX_STORED`) is
intentional map-decoration fading, not a gap. Real LLM memory growth
continues to be addressed at the llama-server-process level
(`LLAMA_RESTART_HOURS`, v0.86.9) per this project's whole standing
history that Python-side RAM has never been the actual source.
`scripts/verify_native_soak.py` byte-identical.

## Current state (v0.87.0)

Explicit user directive, highest priority: push "the LLM learns like a
human" as far as possible in one batch, across every layer (individual
minds, collective/settlement, Town Consciousness/player model,
population-wide reach) and every mechanism (consequence-driven
behavior change, smarter recall, gradual forgetting/distortion, skill
mastery through repetition) — small new LLM call volume approved, main
UI surfacing wanted, remainder scoped into a roadmap doc. Built as two
parallel tracks (see `docs/VISION-2026-07-LEARNING.md` for the full
list of what shipped vs. what's explicitly deferred next).

**`Agent.lessons`** (`llm/beliefs.py`, "smarter recall"): situation-
tagged takeaways (`hunger`/`conflict`/`grief`/`danger`/`social` — a
closed vocabulary so matching stays a cheap deterministic string
comparison, no embeddings), written by extending Reflect() (zero
added call volume). `SimulationEngine._current_situation_tag`/
`_matching_lesson` surface the one lesson matching an agent's CURRENT
situation into `cognition.build_prompt` — the most relevant past
takeaway, not just whatever's newest.

**Memory drift** (`llm/memory_drift.py`, new module, "gradual
forgetting"): the one deliberately new, rare LLM call this batch adds
(core-cast, monthly round-robin, further gated to 20% chance) —
reinterprets one of an agent's older memories in place, same
distortion-via-existing-mechanism scoping `InterpretRumor()` already
established for rumors. Non-critical; fallback is a genuine no-op
(leave the memory untouched).

**Trait consequences + skill-mastery narration** (population-wide,
zero LLM cost): reconciliation nudges sociability up, illness recovery
nudges resilience up — missing positive counterparts to existing
negative nudges. Crossing `MASTERY_THRESHOLD` on any skill now plants
a durable memory + `skill_mastered` event alongside the existing
ambition nudge.

**Settlement pattern-beliefs**: `Settlement.pattern_signal_counts`
(`dispute_feud`/`starvation_death`, same accumulate-threshold-reset
shape as `ritual_signal_counts`) feeds one deterministic "pattern
noticed" sentence into the monthly beliefs job once a count crosses
`PATTERN_SIGNAL_BELIEF_THRESHOLD=3` — the town can now form a belief
about a RECURRING hardship, not just the freshest single event.

**Consciousness player-pattern trend**: `_player_intervention_trend`
(90-day rolling comparison) feeds one deterministic line into the
monthly consciousness prompt. Dev-console/raw-state only — the one
piece of this batch NOT in the main UI, per Phase G's standing
ambiguity-discipline exception for consciousness/player_standing-
adjacent state.

**UI**: new "Lessons learned" NPC-inspector section; new `lesson`/
`episodic_drifted` memory-log kind labels.

Verified: direct tests against the real production code paths for
every piece above (lesson formation/matching/eviction, memory-drift
in-place replacement, reconciliation/recovery trait nudges, mastery
narration, pattern-belief sentence injection + counter reset,
consciousness trend computation); round-trip + legacy-snapshot
defaults for `Agent.lessons`/`Settlement.pattern_signal_counts`;
`scripts/verify_native_soak.py` byte-identical across multiple runs.

## Current state (v0.86.9)

Direct response to a live report: "LLM memory usage... still increasing
and swapping has increased for very long runs." Re-audited every
capped/pruned in-process structure this project tracks — everything
confirmed still correctly bounded, nothing newly unbounded since the
last pass. Verified live (not just by inspection): a synthetic soak
(fake instant-responding LLM client so the full scheduling path runs
at volume, population run from 40 to its cap) showed hearthmind's own
RSS plateauing in step with population rather than climbing
independently — consistent with this project's whole prior audit
history that swap pressure traces to the LLM server side, never this
process (see "Diagnostic history index" below).

Fix targets the mechanism the Python-side audit can't reach: llama-
server's own process heap over a genuinely long uptime. New
`LLAMA_RESTART_HOURS` (`scripts/run.sh`, default `0`/off): restarts
llama-server on a real-time cadence to reclaim general heap
fragmentation that `--defrag-thold`'s KV-cache-only defrag can't touch
— matches the reported symptom shape exactly ("climbs on very long
runs," not short ones). `start_llama_server`/`wait_llama_ready` were
extracted into reusable functions (zero behavior change verified for
the default off path) so a background-subshell restart supervisor can
call the same launch/readiness logic, coordinating through a pidfile
since a subshell can't write back to the parent's `$llama_pid`.
hearthmind.server needs no changes to survive a restart — an LLM call
during the gap fails over to the existing deterministic fallback/defer
path exactly as any timed-out call already does.

Verified: a live smoke run of the unmodified default path confirms
identical startup/shutdown behavior; a live run against a mock
llama-server (a minimal `/health`-answering HTTP stub) with a
shortened restart interval confirms the supervisor correctly cycles
processes, updates the pidfile, and `cleanup()` on SIGTERM stops
whichever pid is current — zero orphaned processes, hearthmind's own
tick loop unaffected through the restart window.

## Current state (v0.86.8)

Explicit user directive: a UI polishing pass on `hearthmind/interface/
static/` for the panels v0.86.3–v0.86.7 landed functionally but never
gave a dedicated visual pass (`life_digest`/"Full life history" memory
log, `belief_digest`/`culture_digest`, "Repairs & upkeep"/"Husbandry"
stat tiles). CSS-only (`style.css`) — no backend files touched.

Real inconsistency found: `belief_digest`/`culture_digest` sit right
above `#beliefs-list`/`#traditions-list`, but only `#traditions-list`
had ever been opted into the project's flat divider-list styling
(shared with `#event-log`/`#infrastructure-list`) — `#beliefs-list`
and, the same gap, `#folklore-list`/`#rituals-list`/`#inventions-list`/
`#festivals-list`/`#records-list` were still on the browser's default
bulleted `<ul>`, so the two new digest panels read inconsistently next
to each other despite being twins in the code. Extended the flat-list
selector group (and its `min-height: 200px` anti-panel-jump partner) to
cover all of them; gave `#belief-digest`/`#culture-digest` their own
block + bottom rule via `:not(.hidden)` (not a bare rule — would tie on
specificity with `.hidden{display:none}` and silently defeat the
toggle, the same landmine `.consciousness-indicator` hit in v0.82.0).

NPC inspector's "Full life history" (`agent_memory_log`, v0.86.3) had
inherited the generic `#npc-inspector-content ul li` 2px-padding rule
shared by every other inspector list — read as a wall of text once
entries (some over 100 words) accumulated. `.npc-memory-log` now gets
its own divider styling, matching the flat-list convention rather than
adding a third one. Verified live with an 18-entry seeded agent (mixed
episodic/semantic/belief/secret kinds): the section's `max-height:
220px; overflow-y: auto` genuinely scrolls (measured `scrollHeight
1209` vs `clientHeight 220`) instead of blowing out the modal, and the
long paragraph entry wraps with zero horizontal overflow.

Minor items while in there: `.event-chip`/`.settlement-chip` had no
`:hover` state — added, matching every other clickable chip/button's
convention. `main`/`header` had no `flex-wrap`; a narrow viewport
forced the sidebar to overlap the fixed-size map canvas instead of
stacking — added `flex-wrap: wrap` to both. **Not fixed, flagged
instead**: the map canvas itself renders at a fixed pixel size and
isn't responsive — a narrow viewport still shows some horizontal
scroll from the map. Making the canvas responsive is a real map-
rendering redesign, out of scope for a polish pass.

Repairs & upkeep / Husbandry stat tiles were already built correctly
against the existing `.stat-tile` convention (audited, no change
needed); map legend colors for pasture/hatchery were already present
in `BUILDING_COLORS` (no separate on-map legend UI exists to update).

Verified live: `python -m hearthmind.server --llm-disabled` against a
throwaway DB seeded with rich state (nonzero digests, buildings/
vehicles repaired, a standing PASTURE/HATCHERY, one agent with 18
durable memory-log rows) + Playwright (pinned chromium): details panel,
NPC inspector with the memory log loaded and scrolled, and a 480px-
viewport pass — zero JS console errors beyond one pre-existing,
unrelated `/favicon.ico` 404.

## Current state (v0.86.7)

Four-part batch per explicit user direction (LLM learning, repair/
upkeep UI visibility, animal+fish husbandry, wider invention scope).

**`Agent.life_digest`**: personal counterpart to `Settlement.belief_
digest`/`culture_digest` — one LLM-authored sentence condensing an
agent's whole self-understanding, written by extending the existing
Reflect() job (zero added calls), fed back into the agent's own
cognition prompt. This is the "read persistent memory back into the
LLM" loop closing at the individual scale — settlement-level digests
already did this via chronicle/town_brain; agents didn't until now.

**Repair/upkeep visibility**: `Settlement.buildings_repaired`/
`vehicles_repaired` — discrete completed-repair counters (crossing back
above `REPAIR_THRESHOLD` for buildings, `BROKEN -> READY` for vehicles;
NOT "condition reaches 1.0" — `_maybe_repair`'s own outer gate stops
touching a building once it clears the threshold, so it almost never
reaches literal 1.0 through this mechanism). New "Repairs & upkeep" UI
tile.

**Husbandry**: `BuildingKind.PASTURE`/`HATCHERY` — deliberate animal/
fish food production, distinct from wild grazer hunting and
opportunistic fish foraging (both pre-existing). Passive trickle +
staffed boost into their own `stored_food`, withdrawable like a
GRANARY. HATCHERY requires a water-adjacent construction site
(`choose_building_kind`'s new `water_adjacent` gate). New "Husbandry"
UI tile + map colors.

**Invention scope**: `llm/invention.py`'s prompt widened to invite
genuinely novel outcomes (husbandry techniques, new food sources,
hardship-born medical remedies) grounded in each settlement's own
history, rather than steering toward a fixed build/farm category list.
Purely a prompt change — mechanical effect (`tech_level += 1`)
unchanged, zero downstream risk.

Verified: direct tests for life_digest write+prompt-reach, the
corrected repair-completion signal, HATCHERY's water-adjacency gate,
husbandry production/capacity/withdrawal, round-trip + legacy-snapshot
defaults; a real 30,000-tick engine run organically founds a standing
PASTURE with zero test-side scripting. Native soak byte-identical.

## Current state (v0.86.6)

Part B of the §4/§7 pass (Part A was v0.86.5's wildlife native port).
Audited `llm/jobs.py`, `llm/client.py`, and the `cognition`/`dialogue`/
`town_brain` prompt builders for redundant fields or oversized token
budgets — all already tight from prior audits (v0.85.3/.4/.5's digest
work, v0.86.0's critical-cognition deferral). Found one genuine wasted-
call case: `_maybe_schedule_folklore` made a real LLM call every
eligible month even with zero rumor events that month, though
`fallback_folklore` already documents the answer is near-guaranteed to
be "nothing worth telling" in that case. Now skips the call entirely
when `rumor_events` is empty (still marks the month resolved, same
observable outcome), unchanged when real rumor material exists — same
pattern `_maybe_schedule_invention`'s prosperity gate already uses.
Verified via a direct engine test with a call-counting fake LLM client
(0 calls / month-resolved on empty rumors, exactly 1 call unchanged
with real rumor material).

## Current state (v0.86.5)

Continues the Constitution §4/§7 roadmap item flagged at the end of
v0.86.0 ("§4/§7: more C++ porting + LLM-call efficiency"). Module 22 of
the R6 opportunistic-port queue: `cpp/src/wildlife_step.cpp`'s
`grazer_tick_step` ports `WildlifeGrid.tick`'s (world/wildlife.py)
GRAZER-branch scalar math (node consumption + overgraze check +
reproduce roll) — a self-contained per-herd computation, unlike the
PREDATOR branch's cross-herd prey lookup, which stays in Python. Audited
every other not-yet-ported physical-substrate module first
(hydrology/terrain_evolution/disasters/farms/buildings decay) and found
all five already native-ported from prior passes — this was the one
remaining candidate with a genuine per-tick loop over un-ported scalar
arithmetic. Verified via 300,000-case randomized equivalence (0
mismatches) and `scripts/verify_native_soak.py` (2 seeds x 1500 ticks,
byte-identical). Part B (LLM-call efficiency) audited in the same pass;
see this file's next update for what was investigated and why no change
was made there this round.

This ran as a parallel background agent in an isolated worktree,
concurrently with v0.86.4's belief/secret durable-history work — see
that section immediately below for what shipped there.

## Current state (v0.86.4)

Direct extension of v0.86.3, per explicit user request to keep pushing
engineered emergent learning further ("do both [belief/secret durable
logging and C++/LLM-efficiency work] in parallel"). `agent_memory_log`
gained `kind="belief"` (every personal belief ever formed/revised,
logged unconditionally in `_maybe_schedule_personal_belief`'s apply())
and `kind="secret"` (every secret ever held, logged at both write sites
— the Reflect()-authored one and the dispute-feud-planted one in
`_maybe_schedule_dispute`). NPC inspector's memory-log labels distinguish
these from generic "memory" now. Verified via a direct engine test that
exercises the real `_maybe_schedule_personal_belief`/`_maybe_schedule_
dispute` methods (not a re-implementation) — 3 belief calls durably log
3 beliefs + 3 secrets with correct text; a real feud (rivalry-seeded
pair) durably logs the correct resentment secret. Native soak
byte-identical.

A parallel background agent worked C++ porting (R6 queue) + LLM-call
efficiency (§4/§7) concurrently in an isolated worktree — see the
v0.86.5 section above for what it shipped.

## Current state (v0.86.3)

Explicit user directive, highest priority: **engineered emergent
learning** — the LLM is never retrained, but the simulation should
appear to learn continuously through persistent, summarized, disk-
backed context, and this must be **visible to the observer** (main UI,
not hidden). Clarified via questions: scope = per-agent AND world/
settlement; visibility = main UI; per-agent mechanism = both raw
retention and distilled summaries.

**Per-agent**: new `agent_memory_log` table (main-UI visible, unlike
`consciousness_log`) — `kind="episodic"` for significant (non-routine)
memories evicted from `Agent.memories` past its cap (8), `kind=
"semantic"` for every distilled self-theory `Agent.semantic_memories`
has ever held. `Population._pending_memory_evictions` (module-level
transient buffer — `_remember` has no reference to its owning
Population/the DB connection) is appended by `_remember`'s eviction
branch (gated `not routine`, matching the existing routine/working_
memory noise-exclusion discipline) and drained by `SimulationEngine.
_tick_once()` each tick. `_maybe_schedule_personal_belief`'s apply()
durably logs every real semantic-memory write — reuses the existing
Reflect() job, zero added LLM call volume. New `GET /agents/{id}/
memory_log` (on-demand, not in the hot broadcast payload) backs the
NPC inspector's new "Full life history" section/button.

**Settlement**: `belief_digest`/`culture_digest` (computed since
v0.85.4/.5, fed into every relevant prompt) were never actually
rendered in the frontend — real gap, now fixed: shown above "The
village's own theories"/"Traditions" panels.

New `Config.agent_memory_log_retention=100_000` (global cap, bounds DB
growth regardless of population size), pruned on snapshot cadence.

Verified: direct unit test (routine-eviction exclusion holds); e2e
engine test (drain + semantic logging); pruning test; live server +
`GET /agents/{id}/memory_log` through the full FastAPI stack; live
Playwright verification (digests render correct text; "Load full life
history" fetches and shows all 6 seeded entries for a test agent,
newest-first; zero JS errors). Native soak (2 seeds x 800 ticks)
byte-identical.

**Deferred, explicitly out of scope this pass**: a dedicated raw-
history browsing UI beyond the NPC inspector (e.g. a standalone "town
archive" panel), and applying the same durable-log pattern to
`Agent.beliefs`/`secrets` (currently still cap-and-evict with no
durable record) — flagged as a natural next increment if the user wants
the pattern extended further.

## Current state (v0.86.2)

§6 follow-up to v0.86.0's Constitution sequencing ("cold information
belongs on disk, not permanently in RAM"). Audited every capped in-RAM
list first: `Settlement.traditions`/`inventions`/`festivals`/`folklore`/
`rituals`/`records` are already durably logged in full via `_log()` →
the `events` table (200k retention) despite their small in-RAM caps —
§6 was already satisfied there. The real gap: `World.consciousness_*`
(Phase N, capped 16/6/2/12) had NO durable record — evicted past the
cap meant forgotten forever.

New `consciousness_log` SQLite table (deliberately separate from
`events` — the consciousness's private memory/theories must never leak
into `recent_events_diverse`, which chronicle/town_brain/beliefs prompts
read). `_maybe_schedule_consciousness`'s `apply()` now logs every entry
there alongside the untouched in-RAM caps. New `Config.consciousness_
log_retention=5000`, pruned on snapshot cadence. `full_diagnostics()`
gained `consciousness.durable_log_count` (dev-console only).

Verified: e2e engine test over ~30 in-game months confirms the RAM cap
stays at 16, the durable count exceeds it, an evicted-from-RAM entry is
still retrievable from disk, and zero consciousness content leaks into
`recent_events_diverse()`.

**Next**: per-agent memory durability (`Agent.memories`/`semantic_
memories`/`secrets` also evict permanently past their caps) is a
larger-scope, higher-volume version of the same gap — deliberately
deferred as its own increment (touches the hot-path `_remember` call
site used across the whole population, not a monthly settlement job).
Then §4/§7: more C++ porting + LLM-call efficiency.

## Current state (v0.86.1)

Module 21 of the R6 opportunistic-port queue: `cpp/src/road_wear.cpp`
ports `RoadNetwork.tick`'s (world/roads.py) per-tile gain/decay scalar
math — same shape as module 20 (`relationship_step`). Sparse dict
iteration/prune-on-fade stays Python. Verified via 400k-case randomized
equivalence (0 mismatches) + native soak (2 seeds x 1500 ticks,
byte-identical).

## Current state (v0.86.0)

First implementation pass against the **Hearthmind Engineering
Constitution** (docs/CONSTITUTION.md, uploaded by the user as the
canonical priority/architecture guide — it supersedes prior audit
reports). It reorders priorities (Emergent cognition > world behaviour >
learning > memory > performance > code quality > deterministic physics >
save compatibility; save-compat is now explicitly the LOWEST priority
and format changes are allowed) and adds one principle that reverses
prior architecture: **"Never replace crucial cognition with simplistic
deterministic fallbacks simply to keep the simulation running. If
cognition falls behind, slow or pause the simulation instead" (§3, §7).**

Previously EVERY LLM job — including individual-mind goal reasoning,
belief revision, the town brain, dreams, and the town consciousness —
resolved to a *fabricated* deterministic substitute whenever the real
call couldn't run (daily budget spent) or failed (timeout/error). This
batch makes crucial cognition **defer instead of fabricate**:

- `SimulationEngine._schedule_llm_job` gained a `critical` flag. For a
  critical job, on budget-exhaustion or an in-flight fallback the
  `apply` callback is NOT run with a fabricated result — state is left
  unchanged and the job re-attempts on its natural cadence. Marked
  critical: `beliefs`, `town_brain`, `personal_belief`, `dream`,
  `consciousness` (the last already hand-rolled a `used_fallback`
  early-return; the flag generalizes it). All other settlement jobs
  (chronicle/tradition/folklore/invention/festival/religion/narrative_
  direction/culture_digest/caravan/omen/naming/record/geography/faction/
  guild_founding/institution_belief/dispute/market_prices) keep their
  deterministic fallback — ambient texture with a sensible objective
  answer, not crucial cognition.
- Per-agent cognition defers too: a core-cast agent at a significant/
  triggered moment that hits the daily ceiling keeps its current
  LLM-authored goal (re-evaluated next staggered slot) instead of
  snapping to `fallback_goal`; `_run_cognition` on timeout/error leaves
  the current goal in place. Physical survival is unaffected — the
  deterministic critical-hunger movement override (D5) still forces
  foraging regardless of goal, so deferring the *goal* call never risks
  starvation. This is the Constitution's deterministic-physics /
  LLM-meaning split working as intended. The significance gate is
  untouched (mundane routines stay deterministic by design, §3).
- The existing live-backlog pacing (`run_forever`/`llm_pressure_paused`,
  v0.82.0) is the "give inference time to catch up" half; this batch is
  the other half — deferred work waits for genuine cognition.
- New `CognitionRunner.calls_deferred_critical` counter, surfaced via
  `stats()` → `/diagnostics.llm_stats` → dev console (same path as
  `calls_dropped_backpressure`, no front-end change). A rising count vs.
  low `calls_succeeded` reads as "the LLM can't keep up and the world is
  correctly waiting," distinct from silent degradation.

Verified: end-to-end engine test — with an always-failing LLM over ~3
in-game months, critical belief jobs form 0 fabricated beliefs,
`current_priority` stays unchanged, `calls_deferred_critical` climbs
(200), while non-critical chronicle fallbacks keep flowing (no
over-deferral); a control run with a working belief client confirms
critical jobs DO mutate state (a real marker belief appears) — the
deferral is failure-specific, not a permanent disable.
`scripts/verify_native_soak.py` unaffected (touches no native module;
the LLM path is disabled in that harness).

**Constitution roadmap (sequenced next, per its own priority order):**
(1) §6 move cold high-level state (consciousness memory/history, culture
lists) to on-demand DB storage rather than always-in-RAM + whole-World
JSON snapshots — the largest structural divergence, deliberately a
separate batch because it changes the persistence boundary; save-compat
is now lowest priority so the snapshot format is free to change.
(2) §4/§7 continue C++ porting of performance-critical systems and add
LLM-call efficiency (prompt caching/batching). Emergence (§1) outranks
both, which is why this scheduling batch came first.

## Current state (v0.85.6)

Three-part batch per explicit user request: fix a live "whispering to
the town brain never visibly does anything" report, make the g++ build
use all available cores, and continue incremental C++ porting.

**Found and fixed the whisper bug**: `POST /intervene/town-brain`/
`POST /intervene/settlement` always wrote to the founding settlement
server-side, ignoring which settlement the UI had selected —
invisible with one settlement, but in a post-fission multi-settlement
world `_maybe_schedule_town_brain`'s round-robin `_job_target()` only
reads a given settlement's queued whisper on that settlement's own
turn, so a whisper aimed elsewhere could sit unread for months. Both
endpoints now accept `settlement_id` (the whisper form sends the UI's
active settlement); `_apply_intervention` resolves the target via
`_settlement_by_id`, falling back to the founding settlement when
omitted. Note this is a real bug fix, not the whole explanation for
every report of "whispering does nothing" — town_brain's whisper was
always designed as "one input among the real stats, not a command"
(CLAUDE.md, "LLM as the town's brain"), so even with correct routing
the model may rationally still pick a priority the real stats point
to; that part is working as designed.

**g++ parallel build**: `setup.py`'s `BuildExtOptional` now defaults
`build_ext`'s `--parallel` to `os.cpu_count()` — a bare `pip install
-e .` (what `scripts/run.sh` runs on every launch) previously compiled
this extension's ~20 .cpp files strictly one at a time. Confirmed via a
live rebuild showing multiple concurrent `cc1plus` processes.

**Module 20 (R6 opportunistic-port queue continues)**: `cpp/src/
relationship_step.cpp` — native fast path for `Population._update_
relationships`'s decay/colocation-gain scalar math, same shape as
module 12 (`bounded_random_walk.cpp`); dict iteration and pairing stay
in Python. Verified via 200,000-case randomized equivalence (0
mismatches) and `scripts/verify_native_soak.py`'s full-state hash
comparison.

## Current state (v0.85.5)

Direct follow-up to v0.85.4, per explicit request: "maybe we can cue an
LLM job occasionally to summarise large prompts." Generalizes the
`belief_digest` pattern to the settlement's accumulated culture/history
(`traditions`/`inventions`/`festivals`/`records`), which — unlike
beliefs — has no natural "revise the whole list" existing job to
extend for free. New `llm/culture_digest.py` + `Settlement.
culture_digest`, written by a genuinely new (but deliberately
infrequent — quarterly, `season_end`, same cadence `narrative_
direction` already uses) `SimulationEngine._maybe_schedule_culture_
digest` job, round-robin `_job_target()`-scoped so volume stays flat
regardless of settlement count. Input bounded by new `CULTURE_DIGEST_
INPUT_MAX=30` so the job's own prompt can't itself grow unbounded.
`chronicle.py`/`town_brain.py` both read the digest as one more
grounding line alongside `belief_digest`. Fallback is a genuine no-op
("no call -> no update this quarter") — `culture_digest` is only
overwritten on a real answer, never fabricated.

Verified: direct tests for `culture_digest.parse_digest`/`fallback_
digest`/`build_prompt`; a real end-to-end engine test confirms the job
fires on `season_end`, writes the digest from a real result, and that
the digest reaches both a captured chronicle prompt and a captured
town_brain prompt; a forced-failure follow-up confirms the digest is
retained, not cleared. `culture_digest` round-trips through `to_dict`/
`from_dict`/`summary()`, legacy snapshots default cleanly. A 3-seed x
15,000-tick engine soak (LLM disabled) completes with zero crashes.

## Current state (v0.85.0)

Batch response to several live requests in one turn: repopulation,
model default, snow probability, dialogue variety, and a doc trim.

**Repopulation from outside**: `Population._maybe_welcome_migrant`
previously only rescued a settlement at near-extinction
(`POPULATION_CRITICAL_THRESHOLD=4`). Now also fires — at a gentler
trickle, `MIGRANT_BELOW_CORE_CAST_CHANCE_MULT=0.25` — whenever world
population falls below `Config.llm_core_cast_size` (default 14),
threaded through `Population.tick(core_cast_target=...)`/`World.
tick()`. Explicit request: a town short of its LLM-authored cast
should draw newcomers "from other villages... outside," not only once
down to a handful of survivors. Verified: near-extinction rate
unchanged, below-core-cast trickle confirmed to fire at its expected
lower rate and correctly not at all once at/above target.

**Default model changed** `qwen3:4b-instruct` -> `gemma-4-e2b-it`
(`Config.llm_model`) per a live "seems to be performing the best"
report — trusted as-is, same standing policy as every prior model-
default change (qwen3.5:2b -> qwen3:4b-instruct, v0.65.2). No other
LLM tuning knob touched; report back real diagnostics if this model
needs its own re-tune rather than guessing ahead of data.

**Snow probability raised**: `SNOW_TEMPERATURE_THRESHOLD_C` 2.0 -> 3.5
(`world/weather.py`), per a live "increase the probability of snow in
winter more" request. Measured first, per the standing unreachable-
threshold lesson: at 2.0C, realized winter snow frequency was only
~1.6% of ticks (precipitation already clears its threshold ~100% of
winter ticks — snow was purely temperature-gated); 3.5C measures to
~16% of Dec/Jan/Feb ticks, still near-zero in November/March.

**Dialogue food-sharing fix**: root-caused a live "conversations always
about food sharing" report — `_maybe_trade_food`/`_tools`/`_medicine`
planted a routine "X shared food with me" memory via `_remember` on
every successful barter (frequent enough to usually BE the freshest
`Agent.working_memory` entry, which `just_now_text` reads
unconditionally for dialogue/cognition's "just now" line). `_remember`
gained `routine: bool` (new `ROUTINE_MEMORY_SALIENCE_MULT=0.5`): still
recorded in episodic `memories` at discounted salience, but never
enters `working_memory` at all. The three trade call sites now pass
`routine=True`. Verified via a direct built-prompt test: a distinctive
memory now correctly surfaces over a routine one.

**Docs trimmed** per explicit request ("trim all the docs... getting
too large and messy"): this file's ~40 oldest version sections
(v0.65.2–v0.81.1) consolidated into one dense summary (2595 -> 1024
lines) — nothing lost, full detail stays in CHANGELOG.md/docs/
DECISIONS.md, which are meant to be the append-only full history per
this file's own framing and were deliberately left alone.
`docs/ROADMAP.md` (a fully-shipped checklist) trimmed to a status
pointer (955 -> ~35 lines). `docs/DECISIONS.md`/`docs/REFACTOR-2026-
07.md`/`docs/REVIEW-2026-07.md` untouched this pass.

**Roadmap status**: docs/VISION-2026-07.md's Phases I-N are all fully
shipped (confirmed while reviewing what "continue with roadmap" could
mean) — no further phase is pre-defined; next direction is whatever
gets asked for next.

Verified: direct unit tests for the migration threshold, routine-
memory salience/working-memory skip, and built dialogue prompt
correctness; a direct 129,600-tick sample confirming snow's ~16.2%
realized winter frequency; a 5-seed x 15,000-tick engine soak (LLM
disabled, mixed population/geography) confirming no crash across all
of the above combined. `scripts/verify_native_soak.py` unaffected —
this batch touches no native module.

## Current state (v0.84.4)

Direct root-cause fix for a live report: "village unnamed till
20kticks, why do some villages not progress at all (no buildings at
all as well)." Traced both symptoms to one cause: settlement naming
gates on a STANDING building existing (`World.tick()`), and
`Population._dispatch_movement`'s GATHER branch had no fallback beyond
a small fixed `GATHER_SEARCH_RADIUS=6` — every other goal-directed
search has one (FORAGE: three tiers; SOCIALIZE: no cap at all), but a
GATHER agent with no FOREST/HILLS tile within 6 tiles got a permanent
`target=None` and degraded to a pure random walk, so `Settlement.
materials` could never cross `HUT_MATERIALS_COST` and the settlement
stayed buildingless (and therefore unnamed) indefinitely.

Fix: new `Population._nearest_material_tile_global` — once the bounded
local scan fails and the agent has no journey already under way, a
one-time reachability-filtered scan (`_reachable_tiles`, the same
flood fill the fission site-chooser/bridge search already use) finds
the nearest FOREST/HILLS tile the agent can actually *walk* to and
sets it as `agent.travel_target`, handing off to the existing
greedy+BFS journey machinery. Filtering by real walkable reachability
(not raw distance) was a deliberate second pass — an initial version
picked nearest-by-distance regardless of reachability, which could
target a real island across a lake/river the journey pathing would
correctly detect as unreachable and abandon, only for the very next
tick's GATHER dispatch to rediscover and reassign the identical
unreachable tile forever (a wasted-effort loop, not a fix). A
settlement whose entire reachable region genuinely has no forest/hills
of its own now correctly stays materials-starved rather than looping —
same "true extinction is a legitimate permanent ending" acceptance
this project already applies elsewhere, not something to force-avoid.

Verified via a direct `_dispatch_movement` unit test (synthetic
terrain, confirms the fallback sets the correct travel_target, the
journey machinery carries the agent there, arrival clears it, and the
local scan then succeeds) plus a real `SimulationEngine` A/B on two
live-generated seeds: a genuinely isolated-island seed stays at
exactly 0 materials/0 buildings both before and after (correct — no
fix should manufacture reachability that doesn't exist); a far-but-
reachable seed goes from 49 buildings pre-fix (materials trickling in
only from lucky population-wide random-walk drift) to 86 post-fix over
the same 20,000 ticks. A 6-seed x 15,000-tick soak (LLM disabled)
confirms no crash across a mix of reachable and unreachable-material
geographies.

## Current state (v0.84.3)

Closes Phase N's full vision-doc intervention menu — the last item,
`misplaced_object`, added directly on top of v0.84.2. Relocates a
partial amount (`MISPLACED_OBJECT_FRACTION=0.4` of the donor's current
stock) of one inventory good (food/tools/medicine) between two
core-cast agents in the founding settlement, capped by the recipient's
own personal capacity — a genuinely mechanical nudge (total quantity
conserved, nothing fabricated), not narration-only, matching the
deterministic-engine-provides-reality priority even at Phase G's small
scale. `ALLOWED_INTERVENTIONS` (`llm/consciousness.py`) now covers all
6 vision-doc menu items. Verified: total-quantity-conserved + exactly-
two-recipients direct test, and a 20,000-tick soak cycling through all
7 intervention kinds (including this one) with zero crashes.

## Current state (v0.84.2)

Direct emergence follow-up to v0.84.0/.1 (per "both in parallel"):
closes the two remaining items `llm/consciousness.py`'s own docstring
had flagged as "not attempted here" — `omen_phrasing_seed` and
`dream_symbol_seed`. `Settlement.omen_seed`/`dream_seed` (new,
`settlement/buildings.py`) queue a phrase, same shape as
`player_influence`, always founding-settlement-scoped regardless of
which settlement's own omen/dream turn it happens to be (the
consciousness is world-scoped). `llm/omens.py`/`llm/dream.py`'s
`build_prompt` each gained an optional seed parameter, folded in with
the same "texture, never a required thread" treatment as
`past_omens`/`folklore`/`narrative_theme`. Retained on a fallback
(cleared only after a genuine success) — same discipline as
`player_influence`. `ALLOWED_INTERVENTIONS` now has 5 of the vision
doc's menu; only a misplaced-object event remains unattempted (would
need a new inventory-shuffle mechanic, not just a reused-state seed).

Verified: direct tests confirm both interventions correctly queue their
seed, both prompts correctly fold in a queued seed, a forced real
`_maybe_schedule_omen` call confirms the seed reaches the actual
engine-built prompt and clears only on non-fallback success;
`omen_seed`/`dream_seed` round-trip exactly, legacy snapshots default
cleanly; a 20,000-tick soak cycling through all five intervention kinds
completes with zero crashes and bounded state.

## Current state (v0.84.1)

Direct observatory follow-up to v0.84.0: Town Consciousness v2's state
was reachable via raw `/state` but not actually surfaced in the
developer observatory panel, unlike `temperament` (already a concise
value in `full_diagnostics()`). Fixed — `renderDevConsole`'s live pane
now includes `payload.summary.consciousness`, and `full_diagnostics()`
gained a `consciousness` key (personality/objectives/memory count/
latest memory/player-model count/latest intervention), same glanceable-
summary-next-to-the-full-lists shape as `temperament`. Reachable via
the dev console's live pane and its "Full diagnostic report" button.
Verified live against a running server (LLM disabled): both `/state`
and `/diagnostics` return the new fields with correct empty-state shape
pre-activity.

## Current state (v0.84.0)

Phase N (docs/VISION-2026-07.md, "The Town Awake" / Town Consciousness
v2), following straight on from Phase M per the user's "continue"
direction. Phase G given a memory and a will — extension, not
replacement: `Settlement.temperament`/`mood`/`player_standing` are
untouched; this is the one monthly LLM call that reads them plus a
small persistent inner state and may choose at most one small,
deniable intervention.

**Persistent inner state** lives on `World` (`consciousness_memory`/
`_personality`/`_objectives`/`_player_model`/`_intervention_log`,
`world/state.py`), not per-settlement — there is one consciousness, not
one per settlement, tied to the founding settlement the same way
player_standing/documentary/whispers already are. `consciousness_
personality` (curiosity/patience/possessiveness) is genesis-seeded
once, deterministically from `config.seed` (`llm.consciousness.
seed_personality`, zero LLM cost) — a settled temperament the monthly
job reasons *from*, not a fourth Phase G random walk. Objectives (cap
2) are revised only when the model actually supplies new ones; the
player model (cap 6, same shape as `Settlement.beliefs` entries but
never institution-mirrored — this is the consciousness's own,
possibly-wrong theory about the *player*, not a village belief) prunes
its weakest-confidence entry past the cap, same discipline as
`Settlement.beliefs` itself.

**Monthly consciousness job** (`llm/consciousness.py`,
`SimulationEngine._maybe_schedule_consciousness`, `MONTHLY_JOB_DAY[
"consciousness"]=24` with the standard retry window, one call): reads
memory/personality/objectives/player-model plus the settlement's real
temperament/mood/narrative-theme/player_standing, and may choose at
most one intervention from `llm.consciousness.ALLOWED_INTERVENTIONS`.
**Deliberately scoped to three of the vision doc's fuller menu**
(also names omen-phrasing/dream-symbol seeds and a misplaced-object
event) — the three chosen ride existing state with zero new cross-
module plumbing: `weather_nudge` perturbs `World.weather` directly
(bounded within the range `compute_weather`'s own smoothed output
actually realizes — the standing "unreachable threshold" lesson
applies to nudges too — and decays naturally through the existing EMA
blend the very next tick, no separate "active nudge" state to expire);
`temperament_nudge` uses a new `extra` parameter on `tick_temperament`
(the shared `bounded_random_walk_step` primitive from module 12
already supported this `value*mean_reversion + jitter + extra` shape,
just not threaded through this call site until now — consumed
one-shot by the very next `_maybe_tick_temperament`, for the founding
settlement only); `false_memory` plants a fabricated-but-plausible
memory on a core-cast agent via the existing `_remember`. **Emotional
contagion** (the vision's "two agents receiving the same seed in the
same month"): `false_memory` also plants the identical text on the
chosen agent's most-bonded living partner, opportunistically (skipped
if none) — achieved as a free side effect of the mechanism already
being built rather than separate dream-seed plumbing.

**Fallback is a genuine no-op** — the one deliberate departure from
every other Phase L/M job's fallback shape (compare `religion.
fallback_religion`/`narrative_direction.fallback_direction`, both real
deterministic answers): "no call -> no intervention that month," per
the vision doc's own explicit framing. `SimulationEngine`'s `apply()`
checks `used_fallback` directly and returns immediately rather than
routing through `parse_consciousness` for that case — a flaky/
overloaded LLM stretch means the town simply doesn't notice or act
that month, never a fabricated substitute.

**UI**: `consciousness_intervention` event icon (🌫️, deliberately the
same glyph as `omen` — an intervention is meant to read exactly like
one), grouped under the "mind" filter chip. No main-UI panel, matching
Phase G's standing ambiguity discipline exactly as it already applies
to temperament/mood/player_standing (none of which appear in index.html/
app.js either) — reachable only via the dev console/raw `/state` JSON
(`World.summary()`'s new `consciousness` key).

Verified: direct fake-client tests confirm the monthly job writes
memory/player-model/objectives/personality correctly from a real
result, `false_memory` plants on exactly one core-cast agent plus its
bonded partner (contagion), `weather_nudge`/`temperament_nudge` stay
within their documented bounds; the fallback path is confirmed to be a
genuine no-op, never a fabricated memory or logged intervention;
`consciousness_*` fields round-trip exactly through to_dict/from_dict,
legacy snapshots default cleanly to empty; a 20,000-tick engine soak
(fake instant LLM client, population 25) completes with zero crashes
and bounded memory/intervention-log lengths. `scripts/verify_native_
soak.py` unaffected — this batch touches no native module. Next
milestone: continued UI/observatory work per the "keep both moving in
parallel" direction; no further roadmap phase has been explicitly
green-lit yet.

## Current state (v0.83.0)

Phase M start (docs/VISION-2026-07.md, "Faith & Meaning"), per explicit
user direction ("Both together, Phase M first" / "keep both moving in
parallel" — Phase N and continued UI/observatory work follow this).
Two pieces, both scoped tightly to the vision doc's own "maximize
emergence per LLM call" arithmetic: ritual/religion spends real LLM
budget only once real accumulated texture exists to ask about; Narrative
Direction is one quarterly call whose entire output is a short ambient
bias string, never an event trigger.

**Ritual detection is free and deterministic** (`SimulationEngine.
_detect_ritual_signals`/`_maybe_promote_ritual`, runs every tick,
cheap even so — bounded by `MAX_SETTLEMENTS`). Two recognized
patterns, matching the vision doc's own examples: `communal_feast`
(enough festivals held — `festivals_held` is already a persistent
counter, and every real festival is already implicitly "after good
fortune" since `_maybe_schedule_festival` only fires when well-fed) and
`shrine_mourning` (a death lands the same tick a STANDING shrine
exists — deaths are settlement-agnostic in `last_life_events`, so this
counts a world-wide death tick against every settlement with a standing
shrine, an acceptable looseness for texture-only heuristics). Promoted
into `Settlement.rituals` (capped `RITUAL_MAX_STORED=12`) at
`RITUAL_PROMOTION_THRESHOLD=3` occurrences, logged as `ritual_formed`.

**Religion crystallization spends the one real LLM call**
(`llm/religion.py`, `_maybe_schedule_religion`, season_end-gated —
requires ≥1 accumulated ritual and no existing religion): asks the
model to honestly judge whether the settlement's rituals/omens/
folklore genuinely coalesce into a shared named belief, or whether
it's still too soon — same "None is not a failure, it's the expected
common case" discipline as `llm/folklore.py`. `fallback_religion()`
always answers "not yet"; a religion is never fabricated by a
fallback. A formed `Settlement.religion` (name + up to 4 tenets) is
also pushed as one representative entry into the existing `Settlement.
beliefs` list — institution-mirrored via the existing `sync_family_/
council_/guild_beliefs` helpers — rather than building a parallel
consumption pipeline, so dialogue/cognition prompts that already read
`beliefs_about`/settlement beliefs pick it up for free.

**Schism on fission**: `llm/fission.py`'s existing per-fission LLM call
gained one optional `schism` boolean field (zero added call volume) —
a departing party from a settlement with a formed religion may choose
to reform it independently on the new settlement, tagged `"Reformed
<name>"` with `schism_of` set to the parent settlement's id and the
parent's tenets carried over unchanged. Deliberately scoped to
fission only, not any dispute/faction-driven schism path — no
faction-religion linkage exists in the codebase yet, and inventing one
felt like unwarranted scope creep for a first version.

**Narrative Direction** (`llm/narrative_direction.py`,
`_maybe_schedule_narrative_direction`, season_end-gated, one call —
a season already IS a real-calendar quarter, no new cadence machinery
needed): reads the settlement's recent events/folklore/mood trajectory
and names the theme(s) actually running through its recent life
("quiet renewal," "unease," "decline") — grounded, never invented
drama. Consumed ONLY as one short ambient-bias sentence
(`_narrative_theme_bias`) folded into `town_brain`/`omens`/
`chronicle`/`Dream()` prompts — it never schedules or scripts an event
on its own; it makes what those mechanisms already do thematically
coherent from call to call instead of arbitrary. Stored capped
(`NARRATIVE_THEMES_MAX_STORED=8`).

**UI**: new "Faith & rituals" panel (religion name/tenets + ritual
list) alongside Folklore under the existing "📊 details" toggle, and a
"recent theme of village life" line in the Town Brain panel — same
per-batch UI-surfacing discipline as every prior phase. Three new
event icons/groups (`ritual_formed` 🕯️, `religion_formed` ⛩️,
`narrative_direction` 📖, grouped under the "mind" filter chip).

Verified: direct fake-client tests for `_detect_ritual_signals`/
`_maybe_promote_ritual` (both patterns promote correctly from
synthetic festival/death history), `_maybe_schedule_religion`
(crystallizes only once a ritual exists, never re-forms an existing
one), and schism-on-fission (correctly tagged reformed offshoot
religion on the new settlement, tenets carried over); `religion`/
`rituals`/`ritual_signal_counts`/`narrative_themes` round-trip exactly
through `to_dict`/`from_dict`, legacy snapshots missing them default
cleanly; live Playwright verification of the new UI panel/line
rendering real injected data; a 20,000-tick engine soak (fake instant
LLM client, Phase M jobs active) completes with zero crashes and
healthy LLM stats (1728 calls attempted/succeeded, 0 errors — no
ritual/religion formed in this particular low-stimulus run, expected
since it's a stability soak rather than a targeted stimulus test, and
formation was already confirmed correct under controlled conditions in
the fake-client tests above); `scripts/verify_native_soak.py`
unaffected — this batch touches no native module. Next milestone:
Phase N (Town Consciousness v2) per the user's explicit direction, plus
continued UI/observatory work in parallel.

## Current state (v0.82.0)

Explicit user directive, and a new standing priority statement: **"the
emergence... is top priority and we will not trade off for that. All
other systems... should augment the LLM based emergence and not work
independently."** Concretely: when simulation throughput and LLM
decision quality compete for the same resource, LLM quality wins —
codified below, not just followed once. Three parts: backend tick
pacing, two frontend bugs/gaps, and a first UI feature that makes an
LLM-authored moment visible on the map itself rather than only in
sidebar text.

**LLM-pressure-aware tick pacing** (`SimulationEngine.run_forever`):
direct response to a live diagnostic showing `llm_backlog_effective`
at 12 against a `_current_backpressure_limit()` of 6 (2x over) with
`calls_dropped_backpressure` at 3006 against only 134 real calls
attempted — the tick loop kept generating new scheduling opportunities
every ~1 real second regardless of whether the 12 already-in-flight
calls (20-40s each on this hardware) had any chance to drain, so almost
every new opportunity was born already-doomed to be dropped. New
`llm_pressure_ratio()`/`llm_pressure_paused()`/`_llm_pressure_interval_
multiplier()`: below `LLM_PRESSURE_SLOWDOWN_START_RATIO` (1.0, at/under
the adaptive limit) nothing changes; between 1.0 and `LLM_PRESSURE_
PAUSE_RATIO` (2.0) the real-time gap between ticks stretches linearly up
to `LLM_PRESSURE_MAX_SLOWDOWN` (6x); at/above 2.0 ticking stops outright
(same `PAUSED_POLL_SECONDS` polling the user's own pause button uses)
until backlog drains back down. Fewer new ticks means fewer agents
becoming "due" for cognition/dialogue per unit of real time (eligibility
is tick-count-based), which is what actually relieves pressure — the
already-in-flight calls keep draining at their own real-time pace
regardless of tick rate. The existing drop-based backpressure/adaptive-
limit machinery is unchanged and still the real safety valve for a
genuinely pathological backlog (this mechanism only needs to buy the
common case — a bursty spike — a real chance to resolve as genuine LLM
answers instead of fallbacks). Surfaced in diagnostics/broadcast as
`llm_pressure_ratio`/`llm_pressure_paused`.

**Frontend: snow bug found and fixed.** Live report: "when it snows it
is not visible in the effects or on the live map." Verified directly in
a real browser (Playwright) rather than guessed: `spawnWeatherParticles`
only ever set a particle's `snow`/`speed`/`drift`/`size` fields at
CREATION time — the spawn loop only appends NEW particles once the
array is below its target count, so any particle already on screen from
a moment ago (most commonly: rain, since rain and snow both require
real precipitation and a rain-to-snow transition is a common real
sequence, not rain-to-clear-to-snow) kept behaving as its OLD weather
type forever. A transition from clear sky (zero particles) was
unaffected, which is why this was easy to miss in a quick check.
Confirmed via a forced rain->snow transition in a live page: before the
fix, particles stayed 100% rain-typed after `is_snowing` flipped true;
after the fix, 100% convert to snow-typed on the very next frame. Also
added a pale ground-tint overlay when `is_snowing` (real snowy days
read bright/overcast-white, not gloomy — distinct from and drawn
instead of rain's darkening tint) for a map-level "it's snowing" cue
that doesn't depend on noticing sparse falling particles. Caught and
fixed a second, self-inflicted bug while building the next feature
below: `.consciousness-indicator`'s bare `display:flex` rule tied on
CSS specificity with the shared `.hidden{display:none}` rule and won by
source order, silently defeating the show/hide toggle — fixed via
`:not(.hidden)`, a specificity-safety pattern worth reusing for any
future toggled element that needs its own `display` value.

**UI: two new "the town is alive" cues**, both reading real backend
state, not decorative: (1) a header "the town is thinking…" /
"deep in thought…" indicator (`llm_pressure_ratio`/`llm_pressure_
paused` from the pacing feature above) — the simulation visibly
choosing quality over speed is now something a player sees, not just a
`/diagnostics` number; (2) a brief pulsing ring over a core-cast agent's
map position the instant a genuine LLM-authored exchange lands
(`dialogue`/`dialogue_surfaced` events, which are logged only for real
core-cast conversations, never the deterministic crowd fallback — see
v0.73.0's `is_llm` gating) — parses the two agent names back out of the
existing `Name: "line" — Name: "line"` event description (best-effort,
cosmetic; a name-parse miss just skips the flash) rather than widening
the event schema for a purely visual effect. Both verified live via
Playwright screenshots, not just read through.

Verified: direct unit tests for the pacing ratio/multiplier/pause
thresholds and a `run_forever` test confirming zero ticks advance while
pressure stays severe; a live browser test forcing a rain->snow
transition confirming all particles convert; a live browser test
confirming the consciousness indicator's hidden/slowed/paused states
render with correct text and are hidden at rest (after the CSS fix); a
live browser test confirming thought-flash rings appear at the correct
agent position for a synthetic dialogue event.
`scripts/verify_native_soak.py` (2 seeds, 1500 ticks) byte-identical —
this batch touches no native module.

## Consolidated history (v0.65.2 – v0.81.1)

Full narrative/verification detail for every entry below lives in
CHANGELOG.md and docs/DECISIONS.md — this section keeps only durable
facts (mechanisms still active, constants still in force) so CLAUDE.md
stays a working reference, not an archive. Trimmed 2026-07 per explicit
user request ("trim all the docs and keep recent few details only").

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
  decayed away — see "Current state (v0.85.1)"). Historical note: the
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
