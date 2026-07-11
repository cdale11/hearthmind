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

- **B1. Ollama client + job architecture.** Async client, prompt
  templates, structured (JSON-mode) output parsing, timeouts with
  deterministic fallback (the LLM must never be able to stall the tick
  loop), and a priority job queue: tick-critical (none, by design) vs.
  cognition vs. background enrichment. This is where the BOINC-style
  idle-CPU model gets built — a worker pool sized to available cores
  minus reserved headroom, continuously consuming the job queue.
- **B2. Sparse agent cognition.** LLM invoked per-agent on a slow cadence
  (roughly once per in-game day, or on significant triggers — a hunger
  crisis, a nearby death, a stranger arriving) to set a goal or
  disposition, which deterministic systems then execute tick-by-tick.
  Decision-first, not dialogue-first.
- **B3. World chronicle / narrator.** Periodic LLM summarization of
  recent events into a persistent history log. This becomes long-term
  memory the LLM itself reads back in later prompts (B2, and later
  culture/horror layers), and it's the first real content for the future
  browser's "history" panel.

## Phase C — Settlements & construction

Buildings (an agent/B2 decision), roads connecting them, construction as
a multi-tick process with resource cost, weathering/decay tied to weather
exposure (already simulated) and disuse, repair as another agent
decision, and abandonment leading to nature reclaiming untended tiles.
Where "prosper, stagnate, or disappear" becomes visible at the
settlement level, not just per-agent.

## Phase D — Agriculture & economy

Farming (building on A1's foraging), storage/granaries (finally gives
starvation death some texture instead of a countdown), production
chains, trade between agents/settlements, a simple currency or barter
system. Economic decisions are natural B2 territory.

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
