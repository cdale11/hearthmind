# Roadmap

This is the long-term plan for Hearthmind, organized into phases rather than
strict version numbers (see `CHANGELOG.md` for what's actually shipped).
Two design principles drive the ordering below:

1. **The LLM is expensive and slow relative to a tick.** It cannot run
   per-agent-per-tick on modest hardware. The architecture separates
   deterministic, cheap, every-tick simulation (physics, needs, movement,
   decay) from sparse, LLM-driven, high-level decisions (goals,
   relationships, culture) made periodically and then executed by the
   deterministic layer over many subsequent ticks. This split needs to
   exist *before* the LLM is wired in, which is why LLM infrastructure
   (Phase B) comes earlier than "add the LLM once everything else exists."
2. **Idle-CPU utilization is an architectural constraint, not a feature.**
   A background job-queue/worker-pool model (tick-critical work vs.
   enrichment work) needs to exist before LLM cognition and
   history-generation land, or they'll either starve the tick loop or
   leave cores idle. Phase B builds this once, and every later phase that
   wants LLM involvement is just another consumer of that queue.

## Phase A — Close the deterministic substrate

Finishes what Milestone 2 slice 1 (agent needs/movement) opened.

- **A1. Foraging & food economy.** Discrete, depletable resource nodes
  scattered across forageable terrain; hungry agents forage them; nodes
  regenerate slowly. Closes the M2-2 gap where hunger only ever rose.
- **A2. Aging, starvation death, old-age death.** Agents track age and a
  per-agent lifespan; sustained starvation or old age removes them from
  the population.
- **A3. Lightweight relationships & birth.** Proximity-based affinity
  between agents; mature, healthy, sufficiently-affinitied pairs can
  reproduce, gated by a hard population cap as a safety valve. This is
  deliberately *not* LLM-driven — it's cheap, deterministic scaffolding
  that gives the Phase B LLM something real to reason about later.

## Phase B — LLM infrastructure (the foundation, not a feature)

- **[x] B1. Ollama client + job architecture (slice 1 shipped).** A
  stdlib-only (`urllib`) blocking client wrapped in an async, bounded-
  concurrency `CognitionRunner` (`hearthmind/llm/`) — this is the
  BOINC-style idle-CPU lever described in the project brief: Ollama's own
  thread pool does inference, and `llm_max_concurrent` controls how many
  requests are in flight to keep it busy. Every call has a timeout and a
  deterministic fallback and never raises into the tick loop. Tested
  against a fake local server; **not yet verified against a real Ollama
  install** — see README. Not yet built: a true priority queue
  distinguishing cognition vs. background-enrichment work — at current
  scale (single population, no chronicle backlog) a flat semaphore was
  enough; revisit once Phase C/D add more LLM-consuming subsystems.
- **[x] B2. Sparse agent cognition (slice 1 shipped).** Agents get one of
  four fixed goals (wander/forage/socialize/rest) once per sim-day,
  staggered across the day, executed deterministically by `Population`'s
  movement logic every tick until re-evaluated. Decision-first, not
  dialogue-first, per the plan above. Not yet built: triggers beyond the
  daily cadence (a hunger crisis, a nearby death, a stranger arriving),
  and goals richer than the current four.
- **[x] B3. World chronicle / narrator (slice 1 shipped).** Seasonal LLM
  summarization of recent events into the existing `events` table
  (category `chronicle`). This is early long-term memory content, not
  yet read back into later prompts (B2's agent cognition doesn't consult
  it) — that's the natural next slice once culture (Phase E) needs it.

## Phase C — Settlements & construction

- **[x] C1-C4. Buildings, construction, weathering, repair, reclamation
  (slice 1 shipped).** Colocated, mature, healthy agents may found a
  building (deterministic in this slice, mirroring A3's reproduction
  mechanic — not yet an LLM/goal decision, see `docs/DECISIONS.md` C1);
  any awake agent present advances construction or repairs a damaged
  standing building; weather-driven decay turns neglected buildings into
  ruins; long-abandoned ruins are eventually reclaimed and removed. This
  is where "prosper, stagnate, or disappear" becomes visible at the
  settlement level, not just per-agent.
- Not yet built: roads connecting buildings, resource *cost* for
  construction (currently free beyond agent presence/time), building
  types beyond a single generic structure, and — the natural next
  slice — tying `AgentGoal`/LLM cognition into *where* and *whether* to
  build, rather than the current pure-chance placement.

## Phase D — Agriculture & economy

- **[x] D1. Farming (slice 1 shipped).** Any awake agent can plant a
  farm plot on grassland; it grows automatically over time and yields
  substantially more food than wild foraging once ready — `Population`
  prefers a ready farm over wild forage whenever one's available.
- **[x] D2/D4: social dispersion found and fixed.** D2 found that farming
  let agents survive indefinitely alone, with no pressure to cluster.
  Root-caused to two concrete bugs, not a deep design gap: SOCIALIZE's
  target search shared FORAGE's local radius (too small for the map, and
  once agents drifted apart there was no way back), and the deterministic
  fallback (used whenever Ollama is off) never chose SOCIALIZE at all.
  Both fixed in D4. **Verified with the exact 30-agent/48x48 run that
  previously produced zero clustering:** the same config now produces a
  self-sustaining, multi-generational population — 30+ births, a
  repeating building lifecycle across 8+ structures, and the first
  old-age death observed in any soak test, sustained for ~3 sim-years.
  See `docs/DECISIONS.md`, D2/D4.
- **[x] D3: starvation trap found via live Ollama play, fixed.** The
  first real run against live Ollama (not a fake test server) surfaced a
  bug where a correctly LLM-assigned FORAGE goal was never executed
  because resting blocked all foraging, with nothing able to interrupt
  rest for a hunger emergency. Fixed with a critical-hunger emergency-wake
  mechanism. See `docs/DECISIONS.md`, D3.
- **[x] D5: a second live-play soak run surfaced a related gap and fixed
  it, plus added diagnostics.** A critically hungry but *awake* agent
  whose assigned goal was SOCIALIZE/WANDER had nothing making it
  deliberately seek food until its next once-per-day goal reevaluation —
  D3 only fixed the resting case. Fixed with the same critical-hunger
  override, applied to movement dispatch generally. Also: raised the
  default LLM timeout for 8GB+zram headroom, and added persisted
  diagnostics (`inspect_world` now shows cumulative LLM
  calls/fallback-rate, cumulative deaths by cause, and per-agent
  starving-ticks/maturity countdown) so a population crash or a flaky
  Ollama instance is visible from a snapshot alone. See
  `docs/DECISIONS.md`, D5.
- **[x] D6/D7: FORAGE now targets farms; granaries added.** D6 fixed
  FORAGE never targeting farms (root cause of a 16-death cascade). D7
  added `BuildingKind.GRANARY` — presence-driven stock/withdraw, a
  community food buffer. See `docs/DECISIONS.md`, D6/D7.
- **[x] D8: production chains, slice 1.** New `AgentGoal.GATHER` feeds a
  settlement-wide materials stockpile; construction consumes it for a 2x
  speed boost. See `docs/DECISIONS.md`, D8.
- Not yet built: farm-yield boost from materials, trade between
  agents/settlements, any currency or barter system. Economic decisions
  are natural Phase B (LLM cognition) territory once they exist.

## Phase E — Culture & history

Named traditions, festivals, generational memory, settlement names and
lore — mostly an extension of B3 (chronicle) plus new LLM prompt
templates that read the chronicle back as context. Where the world
starts producing content that surprises its creator.

## Phase F — Browser interface

Deliberately late. Everything through Phase E is server-only and
testable via `inspect_world`. Once there's a rich world to look at,
build: a read-only HTTP/WebSocket API in front of the engine (the engine
never blocks on it, per the Milestone 1 architecture), map view,
telemetry/diagnostics, inhabitant/location inspection, conversation/event
history, and — last — sparse intervention tools (the "nudge" mechanic).
The engine-owns-time invariant makes this safe to build without risk to
the simulation.

## Phase G — Supernatural / psychological horror layer

Explicitly last, explicitly subtle. Once the chronicle (B3) and culture
(Phase E) exist, this is mostly new LLM prompt templates with a
different tone, rare-event triggers, and careful pacing/budget so it's a
seasoning, not a takeover — likely with a config knob to dial intensity,
since this part needs tuning by feel rather than spec.

## Cross-cutting, ongoing at every phase

- **Snapshot scaling.** Flagged since Milestone 1 (`docs/DECISIONS.md`
  M1-4): full-JSON snapshots won't hold up once buildings/history/
  chronicle text accumulate. Needs to become event-sourced or incremental
  probably by Phase C, not later.
- **Backward-compatible migrations.** The pattern established in M2-3
  and generalized in Phase A (detect-missing-key, backfill, log,
  persist-once) is the template for every future save-format change.
- **Docs/CHANGELOG discipline.** Every phase updates `README.md`,
  `CHANGELOG.md`, and `docs/DECISIONS.md` as part of the work, not after.
- **Release testing.** See `docs/TESTING.md` for the checklist run before
  every release, from Milestone 1's CLI onward through the eventual
  browser interface.
