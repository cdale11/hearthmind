# Vision: "The LLM learns like a human" (v0.87.0 and beyond)

**Status: fully shipped.** Originally scoped 2026-07-17 ("push
emergent, persistent, disk-backed learning as far as possible... small
new LLM call volume approved, main UI surfacing wanted"), with a
deferred-items list scoped "for a later roadmap." Everything named —
the v0.87.0 batch and all six deferred items — shipped across
v0.87.0–v0.87.4. Trimmed to a status pointer 2026-07 (same treatment
`docs/ROADMAP.md`/`docs/VISION-2026-07.md` got once fully shipped) —
full mechanism detail lives in CLAUDE.md's "Current state" history for
those versions and CHANGELOG.md.

## What shipped, by layer

- **Individual minds**: `Agent.lessons` (situation-tagged takeaways,
  smarter recall than "just the newest memory"), memory drift
  (`llm/memory_drift.py`, rare monthly reinterpretation of an older
  memory), gradual continuous memory-salience fade + faded-memory
  wording, cross-generational lesson inheritance, LLM-narrated skill
  mastery (`llm/skill_mastery.py`, core cast only), keyword-overlap
  fallback lesson matching, non-core-cast population-wide lesson
  formation (deterministic templates, zero LLM cost).
- **Collective/settlement**: pattern-belief grounding sentences
  (starvation/dispute-feud/disease-outbreak/wildlife-recolonization
  recurrence), dialogue consumption of lessons.
- **Town Consciousness**: intervention-frequency-trend line folded
  into the monthly prompt, later connected to the consciousness's own
  leading player theory; `revises_leading` lets that theory update in
  place (confidence/revision_count/revised_tick) instead of always
  appending a duplicate.
- **Population-wide**: trait-consequence nudges (reconciliation ->
  sociability, illness recovery -> resilience) and skill-mastery
  narration/events, both deterministic and zero LLM cost.
- **UI**: "Lessons learned" NPC-inspector section; `lesson`/
  `episodic_drifted` memory-log kind labels.

Verified per-mechanism in each shipping version's own CHANGELOG.md
entry; `scripts/verify_native_soak.py` byte-identical throughout (no
native module touched by this vision's work).
