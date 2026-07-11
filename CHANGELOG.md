# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versions correspond
to `hearthmind.__version__`.

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
