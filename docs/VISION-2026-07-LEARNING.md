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

## Deferred to a future increment (explicitly scoped out of v0.87.0/.1/.2/.3)

Ordered roughly by how directly it extends what's shipped so far:

1. **Non-core-cast population-wide LESSONS/memory-drift** (as opposed
   to the trait-nudge/skill-mastery mechanics, which already are
   population-wide since they're deterministic). Extending the LLM-
   authored `lessons`/memory-drift jobs beyond the core cast would
   violate the standing "any new per-agent LLM decision must be
   core-cast-gated" rule (CLAUDE.md) without an explicit override — a
   genuinely non-LLM, template-based lesson-formation path for the
   wider population is the shape this would need to take if pursued.
2. **Smarter recall via real semantic similarity**, not the fixed
   5-tag `LESSON_SITUATIONS` vocabulary. An embedding-based retrieval
   layer (or even a cheap TF-IDF-style keyword overlap) would let a
   lesson/memory match a much wider range of "similar situations" than
   the five hardcoded tags — deliberately not attempted this pass
   (no vector DB/embeddings dependency exists in this project yet;
   adding one is a real new-dependency decision, not a small extension).
3. **Cross-generational lesson inheritance.** H7 (inheritance on death)
   already transfers land/goods/a skill bias to an heir — lessons
   aren't part of that transfer yet. "A parent's hard-won lesson passed
   down, imperfectly" is a natural, human, and currently-unbuilt piece.
4. **Gradual forgetting as a genuinely continuous fade**, not just the
   existing salience-based hard eviction + the new occasional LLM-
   authored drift. A middle ground (a memory's salience decaying slowly
   over real elapsed time even without eviction, subtly changing how
   it's phrased when read back into a prompt) is a bigger mechanical
   change than this batch's scope.
5. **Skill mastery narrated by the LLM**, not a deterministic
   templated sentence. v0.87.0 keeps mastery narration zero-cost/
   deterministic (`"Became a master of X after years of practice"`); an
   LLM-authored version ("got better at healing after losing a
   patient," from the user's own original framing) would need to read
   back the specific memories/events that led to mastery — a genuinely
   new, small LLM job if pursued, similar in shape to memory_drift.
6. **Deeper Town Consciousness narrative modeling, round 2.** v0.87.3
   closes the "fold player_model into the trend line" step; the vision
   doc's fuller ambition (a longer-running theory of the player's
   actual *intentions*, synthesized narratively rather than as one
   highest-confidence belief string) is still a bigger, more
   speculative LLM-authored piece if pursued further.

None of these are blocking or half-built — v0.87.0 is a complete,
mechanically real batch on its own; this list exists so "keep expanding
this direction" has a concrete starting point next time, per the user's
own instruction to scope deferred work into a roadmap doc rather than
leave it implicit.
