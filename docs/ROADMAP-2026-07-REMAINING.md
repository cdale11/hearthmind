# Hearthmind — Final Roadmap

Consolidated and restructured per explicit user instruction: "consolidate
the roadmap and summarize everything at the bottom... make a new phase-
based roadmap at the top... this final roadmap should be a final pass and
after completing that should ship the game I always have wanted."

Everything genuinely open across the whole project — Part A (deterministic
Body), Part B (cognitive Mind), Part C (Body↔Mind seam), Tier 5
(HearthBench + the Adaptive Runtime), Tier 6 (learned models), Tier 7
(HCA), and the C++ native-porting backlog — is captured below in
dependency order. Nothing shipped is repeated here; **all shipped history
now lives in `CHANGELOG.md` and `CLAUDE.md`'s "Current state" log**, which
this doc no longer duplicates (see "Shipped so far," bottom). Standing
convention unchanged: this is a reference, not a queue — work starts only
on an explicit "next step"/item-naming instruction, never auto-chained.

---

## Phase 1 — Semantic substrate + the goal-policy flagship

The two Tier 6 items everything else in this roadmap either builds on or
gates behind.

- **L1.1 — Semantic embedding** of the sim's own vocabulary. Not built at
  all. Blocks L2.3 and HCA `F1` below. 6+ real waiting consumers: memory
  retrieval's hand-tuned weights, four text-dedup sites, `Pillar.
  word_overlap`, topic-novelty checks.
- **L2.2 — Goal policy** (the flagship, the largest single remaining Tier
  6 item). Not built. Closed 7-value `AgentGoal` output; two-phase
  curriculum — phase 1 distills the recorder's existing `(structured_
  input -> goal)` pairs (teacher→student), phase 2 reweights by realized
  world outcome so the student can diverge from and exceed the teacher.
  Absorbs planning (`Agent.plan` becomes an embedded input, not a
  separate model). Anti-homogenization mandatory: personality-
  conditioning, an entropy floor (never argmax), deterministic survival
  overrides stay untouched.
- **L2.3 — Semantic retrieval scorer** (gated on L1.1). Merges the audit's
  M3-consumer + M4 into one learned scorer, replacing `agents/agent.py`'s
  hand-set relevance weights + bag-of-words term.
- **HCA `F1` — Semantic pointers** (gated on L1.1). Concept vectors,
  bundling/binding; test: a concept combination generated/judged with
  strictly fewer LLM calls than today.

## Phase 2 — Wire the already-built ML substrate to real consumers

Every one of these shipped as a real, tested, standalone module with no
live production call site — the recurring gap across Tier 6.

- **L2.1** value/consequence model → a real `B2.4`/`L2.2` consumer (needs
  a real accumulated emergence-log/life-events archive from a live
  world).
- **L3.1/L3.2** (LLM cost regressor, workload forecaster) → real call
  sites; needs a real training archive. L3.2's own "true autoregression
  over the `metrics` table" stays a further, distinct open piece.
- **L4.1** belief-confidence calibration → a real consumer; needs a real
  settled-hypothesis history from a live world.
- **L5** the lifelong-learning loop → a real per-model retrain cadence
  (needs a real per-model decision of "what counts as new examples").
- **L6** evolutionary model-genome participation → a real evolutionary
  cadence / `simulation/engine.py` call site.
- **B13.5** evolutionary tunable-set search (`tunable_evolution.py`) →
  a real cadence (built and verified in isolation only).

## Phase 3 — Close the last Tier 7 (HCA) gaps

- **E3, competing-goals half.** The memory-activation half shipped; the
  competing-goals half needs a genuinely NEW per-agent `GlobalWorkspace`
  arbitrating candidate goals — `llm/cognition.py`'s `fallback_goal` is
  still a flat if-chain, not a scored competition. Real new mechanism,
  not a rendering pass.
- **H1, per-domain budgets.** Write-scope enforcement (WORLD/MACHINE/
  OBSERVER) is real; real per-domain budget contention needs a second
  real bidder in the MACHINE or OBSERVER domain, which doesn't exist yet.
- **A real chunk-expiry mechanism for C2's `ChunkStore`.** Currently
  keyed on subject text with no expiry — fine for texture-only musing,
  but it's what blocks safely sweeping `_maybe_schedule_rule_proposal`
  into Stage C's dispatch ladder (a stale cached "no rule" outcome could
  suppress a genuinely-overdue law for a worsening problem indefinitely).
- **Confirm B1's own headline test** ("pillar-level call share rises from
  1.4% to >15%") against a real live production run — the wiring (W1-W4)
  shipped but the number itself was never re-measured live.

## Phase 4 — The two ~200-site live-judgment audits

Both explicitly need individual per-site judgment plus live replay-hash
verification, not a mechanism — real, slow, careful work, never rushed
through in one pass per this project's own "never big-bang" discipline.

- **B3.3** — convert the remaining `ON_DIRTY`/`ON_EVENT` reactivity sites
  (only `institution_dormancy` converted so far, of ~200 candidates).
- **B9.3** — audit ~200 per-tick call sites for timescale mismatch
  against the real `TimescaleLadder`.
- **B4.2, the last two dormancy candidates** — "inactive settlements" and
  "distant wildlife" (of five originally named; three already shipped).
  Both touch real Body-deterministic per-tick simulation and need a
  genuinely lossless elapsed-tick reconstruction design before they can
  sleep safely, unlike their Mind-layer-only siblings.

## Phase 5 — Finish wiring the Adaptive Runtime's remaining pieces

- **B11** hierarchical memory tiering has no real large-persisted-state
  consumer wired to it yet.
- **B12** — only the RAW→archived-digest stage is wired (the emergence
  log). The remaining cascade (EPISODE→SUMMARY→HISTORY→CULTURAL_MEMORY)
  needs a real chronicle/documentary/culture-digest producer chain per
  stage.
- **B14.3** — `batch_size_for_storage` has no real batched-write
  mechanism to size for yet (the snapshot writer is still one `INSERT`
  per row); needs real new design, not a cheap wire-up.

## Phase 6 — HearthBench (build the benchmark itself)

Only `A0` (confirmed reusable pieces) and `A1.1`/`A1.2` (package skeleton
+ import-isolation firewall) exist. Everything else, in dependency order:

`A2` model adapter layer → `A3` prompt library/test definitions → `A4`
scoring ("the judge problem," the doc's own central design fork) → `A5`
the 9 benchmark categories → `A6` structured-output validator → `A7`/`A8`/
`A9` metrics collector/diagnostics/reports → `A10` the HearthBench Score
→ `A11` run modes (unblocks **B15.5**'s `reference_mode`, currently
built but unused for lack of this) → `A1.3` process isolation (gated on
A2+A11) → `A12` web UI → `A13` CI prompt-regression guard (needs the
whole pipeline first).

## Phase 7 — Native performance (opportunistic, not gated on anything)

Not performance-justified today (Ollama/LLM latency dominates the tick
budget, not Python) — pick up only on explicit direction or a genuine
measured need, never a default next step.

- **R8** — agent tick *logic* (`population.py`'s methods, still reading/
  writing through the already-native `AgentStore`) ported to C++. The
  largest remaining native-porting item.
- Re-audit `world/weather.py`'s 3x3 `WEATHER_REGION_GRID` spatial-region
  handling for a real unported per-tile hot loop (the blend function
  itself is already ported; the region grid was never directly
  re-confirmed either way).

## Phase 8 — Residual polish on already-shipped mechanisms

Small, independent, no-dependency-order-required items, each real but
minor relative to Phases 1-7.

- **A2** — `cellular_step`'s fuller fire-spread mechanics (today only
  ignition-SITE is weighted; whether/how-often/how fire actually spreads
  stays the native-backed mechanism, deliberately not forced onto).
- **A3** — whether settlement/culture generation should ever move off
  LLM-authored and onto deterministic procgen stays a real open design
  question, not a closed one.
- **A4** — migrate `RoadNetwork.wear`/gossip contagion onto `FieldGrid`
  proper (currently correct, independent per-tick local rules) — a real
  but purely structural follow-up.
- **A7** — the full graph/shape grammar (layout AND architecture, beyond
  the "zero lineage awareness" gap already closed), plus rules becoming
  LLM-proposable. Both explicitly unattempted.
- **A8** — grammar-based mutation as an alternate generate path (needs
  A7's shape-grammar work landing first).
- **A9** — give `World.location_character()`'s bare wrapper a real
  consumer (a future dialogue/cognition/NPC-inspector location-flavor
  read) — zero callers today.
- **A12** — per-instance material generalization beyond `Building`/
  `Vehicle` — audited, no real consumer motivates it yet.
- **A21** — folklore/legend pipeline unification remains the one
  genuinely open piece ("aspirational, not attempted").
- **A22** — keep adding Emergence API producers as new deterministic
  subsystems ship; open-ended by design, not a single closable task.
- **Part B pillars (B1/B2/B3/B7)** — each has a real first wired job, but
  the FULL "refactor ~55 scattered LLM jobs into acts of five pillars,"
  full observe→interpret→remember→plan→act→reflect cycling everywhere,
  and real (non-round-robin) arbitration all stay open — the same
  underlying refactor Tier 0 named, now ongoing/opportunistic rather than
  blocking (see Phase 9).

## Phase 9 — Standing discipline (perpetual, never "finished")

Not a queue item — re-apply on every relevant future change, forever.

- **A23** — composability-over-content, enforced at review time on every
  new subsystem.
- **A24** — physical-consistency validation stays inviolable as Part B/C
  gain power; re-confirm on every new intention-writing capability.
- **A25** — periodically re-audit LLM call sites: has anything that
  needed genuine judgment become mechanically deterministic?
- **Per-agent cognition's volume-safe mirroring design** — the design
  question (what the volume gate should be, beyond the one narrow
  instance already shipped for core-cast goal changes) stays open;
  three candidate designs never chosen between.
- **Tier 0's mirror-write → pillar-authored conversion** — closed as a
  blocking item, reclassified to ongoing opportunistic maintenance: keep
  converting a site whenever a genuine one is found.
- **Tier 0.5 live-diagnostic re-measurement** — `D1`-`D4`/`D9`, and
  `D10`'s consolidation-coherence half, were all closed by code-level
  audit only (no live LLM server in this environment); re-measure against
  real inference traffic once one's available. Also re-measure every
  weather/disaster threshold constant over a FULL real year before
  further tuning (a past audit only sampled ~90 days and drew two wrong
  conclusions from it).

---

**Once Phases 1-8 close, this is the shipped game** — Phase 9 continues
by design, the same way code review and threshold re-tuning never
"finish" for a live, always-running world.

---

## Shipped so far (consolidated)

Every item not listed above is done. Hearthmind ships: a deterministic
physical Body (terrain/weather/hydrology/ecology/disasters/roads/
farming/construction, largely C++-native) paired with an LLM-authored
Mind across four co-equal pillars (Humans/Village/Nature/Innovation) plus
a fifth, Reflection, observing all four; persistent per-agent/settlement/
institution memory, belief, and culture; the full Tier 7 Cognitive
Architecture (specialists that bid, a real arbitrated global workspace,
impasse-gated deliberation with chunk caching, ACT-R memory activation,
and a Cognitive Observatory UI showing all of it — Stages A-D, G, H
closed in full, Stage E closed but for E3's competing-goals half above);
an Adaptive Runtime (task graph, scheduler, dormancy, hardware-adaptive
tuning, a real escalation ladder) largely wired to production; and a
from-genesis-to-digital-era historical ladder with LLM-steered branching.
Full narrative detail — every version's rationale, root cause, and
verification data — lives in `CHANGELOG.md` (chronological) and
`CLAUDE.md`'s "Current state" log (topical, most-recent-first). This
document no longer duplicates that record; consult those two files for
"why," this one for "what's left."
