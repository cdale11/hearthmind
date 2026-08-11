# Hearthmind — Roadmap

Consolidated and restructured per explicit user instruction: "cleanup
the roadmap docs... summarize work done at the bottom... at the top
create new roadmap of things that are still pending ordered by priority
and blocking release... audit all docs and code." This is the SECOND
such consolidation — the first (v1.34.250) rewrote this file from 6,013
lines to 227; the accumulated per-item shipping narrative since then
(every phase closing out in place, script-by-script) had regrown it to
2,281 lines, the identical bloat class recurring. Cut back down by the
same method: **every item below states only what's still open and why
— the "why it was built this way"/verification detail for anything
SHIPPED lives in `CHANGELOG.md` (chronological) and `CLAUDE.md`'s
"Current state" log (topical, most-recent-first, searchable by version
number), never duplicated here.**

This pass's audit: read this document in full, re-read `docs/REFACTOR-
2026-07.md`/`docs/MASTERCHECKLIST-2026-07-22.md`/`docs/COGNITIVE-
ARCHITECTURE-2026-08-02.md`/`docs/CONSTITUTION.md`/`docs/DECISIONS.md`
in full, and cross-checked every claimed-open item against the live
codebase before keeping it. One real finding corrected in the same
pass: **B5's own prior "SHIPPED, v1.34.61" entry over-claimed** — it
correctly closed the hypothesize→observe→revise loop for `evolve`/
`merge`, but its own parenthetical ("the real affordance/reaction
query... turned out to have already shipped earlier") is wrong;
`llm/ontology.py`'s `build_evolve_prompt`/`build_merge_prompt` still
carry no `discoverable_combinations`/`discoverable_reactions` params —
only `build_propose_prompt` does. Re-opened below. Nothing else audited
this pass was found stale in either direction.

Standing convention unchanged: this is a reference, not a queue — work
starts only on an explicit "next step"/item-naming instruction, never
auto-chained.

---

## Still open, priority-ordered

Genuinely nothing here is release-**blocking** in a hard sense — the
game runs, is stable, and every core system (deterministic Body,
five-pillar Mind, HCA cognitive architecture, Adaptive Runtime,
HearthBench) is real and shipped. "Priority" below means: how much
each item would plausibly still move the needle on the project's own
stated #1 priority, emergence, weighed against how scoped/low-risk it
is to attempt. Group 1 is the closest thing to "worth doing before
calling this finished"; Groups 2-4 are progressively more optional,
larger, or perpetual-by-nature.

### Group 1 — small, scoped, real gaps (do these first if resuming)

- ~~**B5 — Innovation's `evolve`/`merge` paths still skip the
  affordance/reaction grounding `propose` already has.**~~ **SHIPPED,
  v1.34.299.** `build_evolve_prompt`/`build_merge_prompt` gained the
  same `discoverable_combinations`/`discoverable_reactions` params
  `build_propose_prompt` already had, threaded from
  `_maybe_schedule_ontology_evolution`'s one call site (same query
  `ontology_proposal` already runs, reused not duplicated).
- ~~**`Population.carrying_capacity` as a possible learned regression
  target.**~~ **SHIPPED, v1.34.300.** Explicit product decision: yes,
  as a bounded ±25% learned CORRECTION on top of the hand formula's own
  already-clamped output (never a replacement, never able to widen the
  `dynamic_population_cap` safety valve) — see CLAUDE.md's v1.34.300
  entry and `docs/DECISIONS.md`'s matching entry for the full
  reasoning. `hearthmind/ml/carrying_capacity.py`, `scripts/train_
  carrying_capacity_from_world.py`, wired via `Population.carrying_
  capacity`'s new `carrying_capacity_model` param (`None` = exact prior
  byte-for-byte output, verified against `scripts/verify_replay_
  hash.py`).
- ~~**B4.2 — "distant wildlife" dormancy, the one candidate of five
  left unshipped.**~~ **SHIPPED, v1.34.300**, via an explicit product
  decision to accept a deliberate, documented departure from `docs/
  CONSTITUTION.md`'s B15 `TWO_PART_GUARANTEE` for this ONE subsystem —
  a statistical (non-lossless) catch-up on wake, not a lossless
  reconstruction, per CLAUDE.md's own standing "determinism is not a
  requirement" workflow rule. See CLAUDE.md's v1.34.300 entry, `docs/
  DECISIONS.md`'s matching entry, and `world/wildlife.py`'s own
  module-level comment (the primary source of truth) for the full
  reasoning and scope of the exception — every other dormancy candidate
  and every other Body system keeps the guarantee exactly as before.
  `fast_forward_wildlife_population` (closed-form logistic growth/
  decline approximation + a bounded extinction roll),
  `SimulationEngine._update_wildlife_dormancy`.

**This closes Group 1 in full** — resume the next pass from Group 2.

### Group 2 — HearthBench's own remaining SEQUENCED items

Per `docs/HEARTHBENCH-RUNTIME-2026-07-23.md`'s own step order — A0
through step 7 (`A13`'s CI guard) are fully shipped; these are what's
left of step 8 and the smaller named gaps within already-partial items.

- **A5.11 — the world-level emergence run**, the checklist's own final
  item. Gated on **B15.5**'s `reference_mode` (`simulation/
  escalation.py`, real and built — pins the escalation ladder's rung so
  an A/B benchmark run isn't confounded by adaptive cognition-breadth
  changes mid-run) having a real HearthBench-side consumer, which still
  doesn't exist (confirmed via grep — zero references under
  `hearthbench/`). Now genuinely closer than any prior pass, since
  every other prerequisite (`A1.3`/`A8`/`A9`/`A10`/`C5`/`A12.1`-`A12.9`/
  `A4.3`/`A5.1`-`A5.6`/`A6`) is real — this is the only real SEQUENCED
  item left in the whole HearthBench checklist.
- **A7.2** — a system-sampling thread for peak RSS at each concurrency
  level. `C5`'s `peak_rss_mb_by_concurrency` field ships honestly empty
  until this exists.
- **A11.1-A11.3/A11.5** — the fuller quick/full/custom/strict-repro run
  MODE abstraction (today's real slice: a single run mode only).
- **A9.1** — latency/memory GRAPHS in the HTML report. No charting
  dependency exists in this repo yet; real numbers print as a table
  instead today.

### Group 3 — larger, deliberately unscoped, or opportunistic

None of these are gated on anything else; each needs its own real
scoping/design pass before it's a single shippable slice, and none has
been judged worth forcing through prematurely.

- **A7** — the full graph/shape grammar (layout AND architecture, plus
  rules becoming LLM-proposable) — today's real shipped slice is a
  smaller single-rule-per-domain rewrite system, not a full grammar.
- **A8** — grammar-based mutation as an alternate generate path for
  Innovation. Needs A7's fuller shape-grammar work first.
- **A4, gossip-contagion half** — migrating `world/memetics.py`'s
  relationship-graph-based gossip spread onto a coarse spatial
  `FieldGrid` region. Unclear this would even be an improvement over
  the graph-based mechanism already in place; flagged, not attempted
  either way. (The `RoadNetwork.wear`-onto-`FieldGrid` half already
  shipped, v1.34.36.)
- **A10, the whole-food-web-as-one-coupled-system remainder** —
  today's real shipped slice (migration/competition/decomposition/
  pollination/habitat formation, v1.34.94) treats each mechanism
  independently; folding them onto A1's `FieldGrid` substrate as one
  genuinely coupled system is real, larger, unscoped follow-up.
- **A12** — per-instance material generalization beyond `Building`/
  `Vehicle` (e.g. a `Vehicle`'s own material). Audited repeatedly, no
  real consumer motivates it yet — building it without one would be a
  stub, against this project's own standing discipline.
- **R1** (`docs/REFACTOR-2026-07.md`) — `population.py`'s mixin-based
  decomposition. First slice (pathfinding) shipped v1.34.296; the
  doc's own remaining proposed groupings (`_needs`/`_social`/
  `_settlement_ops`/`core`) stay open, one cohesive method-group per
  pass, same "never big-bang against the single largest file with no
  test net" discipline the first slice itself followed.
- **R8** (`docs/REFACTOR-2026-07.md`) — the rest of `population.py`'s
  per-agent tick *logic* ported to native C++ (several scalar functions
  already ported piecemeal since v1.34.291; the majority of tick
  methods remain Python). Explicitly NOT performance-justified today —
  Ollama/LLM latency dominates the real tick budget by orders of
  magnitude over anything Python costs here. Opportunistic only, pick
  up on explicit direction or a genuine measured need, never a default
  next step.
- **Part B pillars (B1/B2/B3/B7) full refactor** — each of the five
  cognitive pillars has a real first wired job and real observe/
  interpret/arbitration machinery, but the full "every one of ~55
  scattered LLM call sites is an act of one of five pillars, full
  cycle everywhere, real (non-round-robin) arbitration everywhere" is
  still only partially realized. Ongoing/opportunistic, not blocking —
  same item Tier 0 originally named, ships one more site at a time.

### Group 4 — perpetual standing discipline (Phase 9, never "finished")

Not a queue — re-apply on every relevant future change, forever. None
of these block anything; they're the project's own maintenance loop.

- **A23** — composability-over-content, enforced at review time on
  every new subsystem.
- **A24** — physical-consistency validation stays inviolable as Part
  B/C gain power; re-confirm on every new intention-writing capability.
- **A25** — periodically re-audit LLM call sites: has anything that
  needed genuine judgment become mechanically deterministic?
- **C4** (`docs/MASTERCHECKLIST-2026-07-22.md`) — "the acceptance gate
  as law": today only two concrete instances exist (`world.ontology.
  retire_stale_rules` for `TriggerRule`, `world.reactions.retire_
  stale_composite_reactions` for `CompositeReaction`); no genuinely
  general "every persistent state has a creator+consumer, reject
  unread state" runtime auditor exists. Enforce as a standing review
  rule; build the general auditor only if a third concrete instance
  makes the pattern worth abstracting.
- **A22** — keep adding Emergence API producers as new deterministic
  subsystems ship; open-ended by design, never a single closable task.
- **Per-agent cognition's volume-safe mirroring design** — what the
  volume gate should be beyond the one narrow instance already shipped
  (core-cast goal changes); three candidate designs never chosen
  between.
- **Tier 0's mirror-write → pillar-authored conversion** — reclassified
  from blocking to ongoing opportunistic maintenance; keep converting a
  site whenever a genuine one is found.
- **Tier 0.5 live-diagnostic re-measurement** — `D1`-`D4`/`D9` and
  `D10`'s consolidation-coherence half were closed by code-level audit
  only (no live LLM server in this environment); **re-measured against
  real inference traffic in 237-tick live run with nemotron-4b-q5_k_m
  (v1.34.301)** — runtime diagnostics framework verified working: ON_EVENT
  gating, per-task call counts/wall-times/idle-ratios, pillar inbox/outbox
  flow, emergence surprise gate (85.7% suppression). `D10`
  consolidation-coherence needs longer run but framework is live.
- **"Confirm B1's headline test live"** (Phase-3-era HCA item) — the
  wiring (W1-W4) shipped; **measured in 237-tick live run with
  nemotron-4b-q5_k_m (v1.34.301)** — runtime diagnostics captured
  pillar-scoped LLM call data across 237 ticks (ON_EVENT jobs:
  beliefs/chronicle/invention/laws/etc. ran 2x on day_end; CRITICAL
  per-tick jobs: due_cognition/due_dialogue/voice_dialogue/dispute/
  naming/record/spread_concepts/spread_tradition_keeping/
  composite_reactions ran every tick). Pillar arbitration framework
  verified live; longer run needed for statistically significant
  pillar-level call share measurement (>15% target), but the
  measurement infrastructure is confirmed working.

---

## Shipped so far (consolidated)

Everything not listed above is done. Hearthmind ships: a deterministic
physical Body (terrain/weather/hydrology/ecology/disasters/roads/
farming/construction, largely C++-native) paired with an LLM-authored
Mind across four co-equal pillars (Humans/Village/Nature/Innovation)
plus a fifth, Reflection, observing all four; persistent per-agent/
settlement/institution memory, belief, and culture; the full Tier 7
Cognitive Architecture (specialists that bid, a real arbitrated global
workspace, impasse-gated deliberation with chunk caching, ACT-R memory
activation, and a Cognitive Observatory UI showing all of it — Stages
A-H all closed in full); a full Tier 6 learned-model substrate (goal
policy, value/consequence model, LLM-cost regressor, belief calibrator,
lifelong-learning + evolutionary retraining, all locally trainable —
see README's "Local ML training" section); an Adaptive Runtime (task
graph, scheduler, dormancy, hardware-adaptive tuning, a real escalation
ladder) wired to production; a complete HearthBench model-benchmarking
harness (adapters, scoring incl. LLM-judge categories, run records,
reports, a web daemon, CI regression guard); and a from-genesis-to-
digital-era historical ladder with LLM-steered branching.

Full narrative detail — every version's rationale, root cause, and
verification data — lives in `CHANGELOG.md` (chronological) and
`CLAUDE.md`'s "Current state" log (topical, most-recent-first, search
by version number e.g. "v1.34.297"). This document no longer duplicates
that record; consult those two files for "why," this one for "what's
left."
