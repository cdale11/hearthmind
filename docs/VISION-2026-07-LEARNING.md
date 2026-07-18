# Vision: "The LLM learns like a human" (v0.87.0 and beyond)

Explicit user directive (2026-07-17): push emergent, persistent,
disk-backed learning as far as possible in one batch, across every
layer at once (individual minds, collective/settlement, Town
Consciousness/player model, population-wide reach), covering every
mechanism discussed (consequence-driven behavior change, smarter
recall, gradual forgetting/distortion, skill mastery through
repetition) — small new LLM call volume explicitly approved, main UI
surfacing wanted. This doc records what shipped in v0.87.0 and, per
the user's own "scope the rest in a roadmap," what's deliberately
deferred as a next increment.

Follows the same pattern `docs/VISION-2026-07.md` (Phases I-N) already
established: audit-before-feature, extend existing systems before
adding parallel ones, "maximize emergence per LLM call."

## Shipped in v0.87.0

- **`Agent.lessons`** (individual minds, "smarter recall not just
  storage"): situation-tagged takeaways (`hunger`/`conflict`/`grief`/
  `danger`/`social`), written by extending the existing Reflect() job
  (zero added call volume), consumed by cognition via a deterministic
  `_current_situation_tag` classifier + `_matching_lesson` lookup — the
  agent's most RELEVANT past lesson surfaces when the matching
  situation recurs, not just the newest memory regardless of relevance.
- **Memory drift** (`llm/memory_drift.py`, "gradual forgetting/
  distortion"): a genuinely new, deliberately rare monthly job
  (core-cast only, `MEMORY_DRIFT_CHANCE=0.2` on top of round-robin) that
  reinterprets one of an agent's older memories in place, same
  "distortion via the existing memory mechanism" scoping
  `InterpretRumor()` already established for rumors, applied instead to
  an agent's own memory some time after formation.
- **Trait-consequence nudges + skill-mastery narration** (population-
  wide, deterministic, zero LLM cost — see the parallel background
  agent's report/CHANGELOG entry for exact constants/call sites):
  reconciliation nudges sociability up, illness recovery nudges
  resilience up (the missing positive counterpart to the existing
  hunger-nudges-resilience-down case), and crossing `MASTERY_THRESHOLD`
  now plants a durable memory + `skill_mastered` event alongside the
  existing ambition nudge.
- **Settlement pattern-belief candidates** (collective/settlement
  layer): the monthly settlement-wide beliefs job now gets a
  deterministic "pattern noticed" grounding sentence when repeated
  feuds/starvation deaths cross a small threshold in a season, so the
  town can form a real belief about a RECURRING pattern, not just react
  to whatever event happened most recently.
- **Consciousness player-pattern window** (Town Consciousness layer):
  a deterministic intervention-frequency-trend helper feeds one more
  line into the existing monthly consciousness prompt. Dev-console/raw-
  state only, per the Phase G ambiguity discipline's standing rule —
  deliberately NOT in the main UI even though this batch otherwise
  surfaces in the main UI, since consciousness/player_standing-adjacent
  state has an explicit standing exception in CLAUDE.md.
- **UI**: new "Lessons learned" NPC-inspector section; new
  `lesson`/`episodic_drifted` memory-log kind labels in "Full life
  history."

## Shipped in v0.87.2

- **Deeper settlement pattern-recognition** — `pattern_signal_counts`
  now tracks `disease_outbreak` and `wildlife_recolonization` alongside
  the original `starvation_death`/`dispute_feud` pair; `_maybe_
  schedule_beliefs` folds in the two new "pattern noticed" sentences
  the same additive way as the original two. Closes item 4 (was item
  5) of this doc's deferred list. Also included, unrelated to learning:
  llama-server glibc malloc-tuning env vars in `scripts/run.sh`
  (`LLAMA_MALLOC_ARENA_MAX`/`_MMAP_THRESHOLD_KB`/`_TRIM_THRESHOLD_KB`)
  as a complement to `LLAMA_RESTART_HOURS` — see CHANGELOG.md v0.87.2.

## Shipped in v0.87.1

1. **Dialogue consumption of lessons** — `dialogue.build_prompt` now
   reads each speaker's situation-matched lesson too, via the same
   `_current_situation_tag`/`_matching_lesson` machinery `cognition.
   build_prompt` already used, threaded through `_schedule_due_
   dialogue`. Zero added call volume. Also included: a fresh audit for
   RAM state that could move to disk-on-demand to curb LLM-related
   memory growth — found nothing new to move (see CHANGELOG.md
   v0.87.1 for the full rationale); `Settlement.records`/`memorials`
   confirmed to already have durable backing beyond their in-RAM caps.

## Shipped in v0.87.3

- **Richer Town Consciousness narrative modeling** — closes item 4
  (below). `_player_intervention_trend` now folds the consciousness's
  own leading `player_model` theory into the frequency-trend sentence
  instead of the two facts sitting unconnected in the prompt. Zero
  added LLM call volume. Also included, unrelated to learning: parallel-
  build hardening, a sim-defaults performance audit (no change — see
  CHANGELOG.md v0.87.3), and `LLAMA_RESTART_HOURS` now pausing the
  simulation with UI/diagnostics visibility instead of relying on
  per-call fallback.

## Shipped in v0.87.4

Explicit user directive: implement all six remaining deferred items in
one batch. All zero-added-LLM-cost except item 5 (a genuinely new,
narrowly-scoped, core-cast-gated call, matching this batch's own
approved small-call-volume budget).

1. **Non-core-cast population-wide lesson formation** — deterministic,
   template-based (`RECOVERY_LESSON_TEMPLATES`/`RECONCILE_LESSON_
   TEMPLATES`, `agents/population.py`), triggered at two existing
   deterministic events (illness recovery, dispute reconciliation) for
   EVERY agent, not just the core cast — zero LLM cost, so the
   standing core-cast-gating rule doesn't apply. Reuses `push_lesson`/
   `MAX_LESSONS` unchanged.
2. **Keyword-overlap fallback matching** (`SimulationEngine._matching_
   lesson`) — when no lesson shares the agent's exact situation tag, a
   cheap stdlib keyword-overlap comparison (`_overlap_tokens`, no
   embeddings/vector DB) against the agent's most recent `working_
   memory` entry surfaces the best-matching lesson if it clears
   `LESSON_KEYWORD_OVERLAP_MIN` shared meaningful words. Exact-tag
   matches still take priority.
3. **Cross-generational lesson inheritance** (`Population._apply_
   inheritance`) — the deceased's freshest lesson passes to their heir
   `INHERITANCE_LESSON_CHANCE` of the time, attributed ("X used to
   say: ...") rather than claimed as the heir's own — imperfect,
   never guaranteed, matching a lesson's real chance of being lost
   between generations.
4. **Gradual continuous memory-salience fade** — new `Population.
   decay_memory_salience()`, called once/sim-day (`day_end`),
   multiplies every stored memory's salience by `MEMORY_FADE_DECAY_
   PER_DAY` (floored at `MEMORY_FADE_FLOOR`) — a memory that's never
   evicted or drifted still slowly reads as hazier. `faded_memory_
   text` (agent.py) rewords a sufficiently-faded memory when it's read
   into cognition/dialogue prompts ("I only vaguely recall: ...").
5. **LLM-narrated skill mastery** (new `llm/skill_mastery.py`,
   `SimulationEngine._maybe_schedule_skill_mastery`) — for core-cast
   agents only, replaces the just-written deterministic mastery memory
   with an LLM-authored reflection grounded in the agent's own recent
   memories, in place (same index-identity-check pattern `memory_
   drift.py` established). Non-core agents and the settlement-wide
   event log are completely untouched — this is personal narration,
   not public record. Genuine no-op fallback.
6. **Consciousness player-theory revision, round 2**
   (`llm/consciousness.py`, `SimulationEngine._maybe_schedule_
   consciousness`) — new `revises_leading` JSON field lets the monthly
   job say a fresh `player_belief` is a refinement of its existing
   leading theory rather than an independent new one; when true, the
   leading `consciousness_player_model` entry is updated IN PLACE
   (confidence nudged up via `CONSCIOUSNESS_REVISION_CONFIDENCE_GAIN`,
   `revision_count`/`revised_tick` incremented) instead of appending a
   duplicate — closes a real gap where those two fields existed since
   v0.84.0 but were never actually incremented by anything.

Verified: direct tests against the real production code for all six
(illness-recovery/reconciliation lesson formation, keyword-overlap
fallback matching including exact-tag-still-wins, inheritance's
imperfect-chance + freshest-lesson-wins + attribution, salience decay
+ faded-text wrapping, a real fake-LLM-client engine test confirming
core-cast mastery narration replaces the memory in place while a
non-core agent's deterministic template and event log are untouched,
and consciousness revision-vs-append branching including the "no
belief -> forced False" guard). `scripts/verify_native_soak.py`
byte-identical.
