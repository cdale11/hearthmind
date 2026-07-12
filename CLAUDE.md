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

8GB RAM + zram swap, CPU-only inference. Default model `qwen3:4b`
(~2.6GB Q4 weights) — moved from `qwen2.5:7b-instruct` (~4.5GB) to a
newer generation (Qwen3, not "Qwen3.5" — that doesn't exist as of this
writing) at a smaller size, generally matching or beating the old 7B's
quality on community benchmarks while leaving more headroom for the
simulation process itself. `qwen3:1.7b` (~1.1GB) is the lighter
fallback if this is still too heavy/slow on the user's actual box —
`--llm-model qwen3:1.7b` and report back, don't silently downgrade the
default without that signal. Qwen3 is a hybrid "thinking" model; every
call disables that (`OllamaClient` sends `"think": false` and
defensively strips any `<think>` block that leaks through anyway) since
every prompt in this project wants one strict-JSON answer, not visible
chain-of-thought eating into the timeout budget. `llm_timeout_seconds=30`,
`llm_max_concurrent=4`. LLM is on by default (`Config.llm_enabled=True`)
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
underfoot (see `World.from_dict`'s legacy-snapshot reconstruction).

A settlement starts in the `industrial` era and can advance
(electrical -> modern -> digital) purely as a function of accumulated
`tech_level` (`buildings.era_for_tech_level`) — each era is a
mechanically real unlock (the FACTORY building kind past `industrial`),
not just a label change.

A brand-new world's seed is chosen by a one-time "genesis" LLM call
(`llm/world_genesis.py`, wired in `server.py`) when `--seed` is omitted:
the LLM writes a short founding-scenario sentence, and its hash becomes
the seed that drives the ordinary deterministic terrain/weather
generation — "initial terrain and weather chosen by an LLM" is literal,
not cosmetic. An explicit `--seed` always wins and skips genesis
entirely; a resumed world never re-runs it.

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

## Known architectural gaps (not yet built)

- Per-agent inventory/trade and multiple named settlements — both
  genuinely large, architecturally separate efforts (the latter means
  `Settlement` stops being a world-wide singleton), intentionally not
  bundled into smaller batches.
- Phase G (subtle supernatural layer) — not started, deliberately last.

## Conventions

- Constants live as module-level values near the dataclass they govern,
  with a one-line docstring explaining *why* the number, not what it is.
- New behavioral fixes/features get a named or lettered decision entry
  in `docs/DECISIONS.md` — root cause (for fixes), design rationale, and
  verification data (manual/ad-hoc, not `unittest`).
