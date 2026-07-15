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
is now the assumed default (`--n-gpu-layers 999`, `Config.llm_num_ctx`/
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
`llm_timeout_seconds=60`, `llm_num_ctx=3072`,
`llm_num_predict=512` (raised from 1280/384 in v0.72.3 once GPU offload
was confirmed working, then re-lowered from an initial 4096/640 in
v0.72.4 once the user's live `htop` reading showed only ~6.5GB usable
RAM rather than the full 8GB nominal — the CPU-only-Ollama KV-cache
pressure that drove the original 1280/384 down in v0.71.1 doesn't apply
the same way with GPU offload, but "GPU offload works" ≠ "unlimited RAM
headroom"; lower back to 1280/384 for CPU-only 8GB hardware, see
README), `llm_keep_alive="3m"`, `llm_use_mmap=True`,
`llm_num_thread=None` (`server.py` CLI defaults `--llm-num-thread` to
every CPU core — see below), `llm_num_gpu=None` for the Ollama backend
(GPU offload for the default llama.cpp backend is `--n-gpu-layers`, a
`llama-server` launch flag — confirmed working via `scripts/run.sh`,
default 999, see README's AMD iGPU section and the iGPU investigation
in docs/DECISIONS.md).

**`llm_max_concurrent=2` is a permanent floor** (explicit user
instruction: LLM richness is never traded off against memory below 2;
further memory savings must come from other levers). History of that
tuning: docs/DECISIONS.md v0.43.0/v0.43.1/v0.44.0. As of v0.63.0 every
`server.py` CLI default references its `Config` attribute — the audit
found `--llm-max-concurrent` had silently stayed at a hardcoded 4 for
several releases, doubling real Ollama concurrency on plain launches.

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
engine provides reality; the LLM provides meaning. NPCs are imperfect:
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

**True water transport**: v0.66.0 shipped RAFT as a settlement-wide
fishing-yield bonus (see "Current state" below), explicitly NOT actual
water-crossing pathing — an agent still can't walk a raft across
`DEEP_WATER`/`SHALLOW_WATER`. A real follow-up (faster fission-journey
crossing, or reaching an otherwise-unreachable site) needs its own
pathing-system pass, not a bolt-on.
