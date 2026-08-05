# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versions correspond
to `hearthmind.__version__`.

## [1.34.244] — Tier 7 HCA Stage E, E3: memory-activation panel (goals half explicitly deferred)

Explicit user instruction: "Start E3."

**E3.** The roadmap names E3 as two panels — "memory-activation and
competing-goals." Investigated first, not assumed: only one half has
real backing state to render. The memory half is real and buildable —
D1 (v1.34.240) already stamps `Agent.memory_ticks`/`memory_salience`/
`memory_causes` on every real memory, unconditionally, whether or not
`retrieve_relevant_memories` is ever called for that agent. The
competing-goals half is NOT buildable as a rendering pass — `llm/
cognition.py`'s `fallback_goal` is a flat sequential if-chain, never a
scored Bid-based competition; there is no real per-agent workspace
arbitrating candidate goals anywhere in production. Building one would
be a genuinely NEW mechanism (a real per-agent `GlobalWorkspace` over
candidate goals with real utilities), not a presentation pass like
every other E-item shipped so far — flagged as real, distinct future
work rather than forced through as a panel over numbers nothing
computes today.

New `hearthmind.cognition.observatory.describe_memory_activation(agent,
current_tick, top_n=10)`: D1's real `memory_activation` formula
(base-level + spreading activation) applied to every real entry in
`agent.memories`, ranked highest-first, bounded to `top_n`. Scored with
`relevance=0.0` throughout — deliberately a standing "what's active
right now" snapshot, not a scored answer to a specific retrieval query
(a real `retrieve_relevant_memories` call supplies its own real
relevance term instead). New `SimulationEngine._memory_activation_
snapshot()` picks the agent via `_observer_favorite_agent()` — the
same real target-selection function Phase G's own interventions
already use, reused rather than inventing a second agent-picking rule
— surfaced via `full_diagnostics()['memory_activation_snapshot']`
(honest `None` before the observer has inspected any core-cast agent).
New dev-console "HCA E3: memory activation" panel
(`renderMemoryActivation`, `app.js`), same plain-formatted-text
presentation discipline every prior E-panel already established.

New `scripts/verify_e3_memory_activation.py` (16 checks — `describe_
memory_activation`'s own correctness against a real `Agent` driven
through the real production `_remember`/`set_current_tick` call path;
a real end-to-end proof through a real `SimulationEngine` confirming
`memory_activation_snapshot` honestly `None` before any inspection,
then populated with the real favored core-cast agent's real memory
once `_record_observer_attention` fires) — all pass, first run, no bug
found.

Verified: the new script (16 checks); `verify_e2_workspace_
activity.py`/`verify_d1_activation.py`/`verify_phase35_w1_naming_
workspace.py` re-run clean (unaffected); `node --check` clean on
`app.js`; `pyflakes` clean on all touched/new files (only the six
known pre-existing forward-ref findings in `engine.py`). No persisted
`World`/`Agent` schema or tick-loop logic changed (`full_diagnostics()`
is a pure read-only diagnostics report) — no replay-hash/native-soak
re-run needed. The competing-goals half remains open — resume only on
future explicit direction naming a real goal-arbitration mechanism to
build first.

## [1.34.243] — Tier 7 HCA Stage E, E2: workspace contents + the losing coalitions panel

Explicit user instruction: "Start E2."

**E2.** Workspace contents + the losing coalitions panel — the
deliberate GWT correction over a plain priority queue (§2.10/§3.3):
"workspace contents AND the losing coalitions." Unlike Stage C, this
one had real production data to show from day one: B1's
`GlobalWorkspace` has been wired into ~54 real `_schedule_llm_job`
call sites since Phase 3.5 (`W1`-`W4`); every real firing already
appends a real `CompetitionRecord` to a real, bounded `GlobalWorkspace.
history`. New `hearthmind/cognition/observatory.py`'s `describe_bid`/
`describe_competition`/`workspace_snapshot` — pure presentation over
that already-real state, same "rendering pass over already-real
backend state, not a new mechanism" shape E5 used for `WorkloadForecaster.
error_history`.

Honest limitation, stated up front in the new module's own docstring:
every one of those ~54 production sites is, by W1/W2/W3's own
docstrings, a real "coalition of one" (submit-then-immediately-
arbitrate at each call site), so `CompetitionRecord.losers` is always
empty in production TODAY — the panel is real and genuinely wired, it
just has nothing to lose against yet. Closing this gap for real is
Phase 8's own job; `describe_competition`/`workspace_snapshot` make no
assumption about coalition size, so they need no change once a real
multi-bid cycle exists.

`full_diagnostics()` gained `naming_workspace_activity` — `workspace_
snapshot(self._naming_workspace, recent=20)`, the real history of
W1's own production pilot workspace (the longest-running real
`GlobalWorkspace` in this codebase). New dev-console "HCA E2:
workspace activity" panel (`renderWorkspaceActivity`, `app.js`), same
plain-formatted-text presentation discipline `renderAdaptiveRuntime
Status`/`renderLearningSpecialistCurve` already established — winner
and every losing bid per cycle, newest first, an honest "(no losing
bids this cycle — coalition of one)" line when `losers` is empty
rather than hiding the field.

New `scripts/verify_e2_workspace_activity.py` (9 checks — `describe_
bid`'s verbatim field mapping; `describe_competition`'s real empty-
cycle case and a genuine hand-built multi-bid cycle proving losers ARE
captured correctly when they exist; `workspace_snapshot`'s bounded/
ordered real-history read incl. the empty-workspace case; an end-to-
end proof through a real `SimulationEngine` — the exact `_make_engine`/
`FakeAdapter` technique `verify_phase35_w1_naming_workspace.py`
already established — confirming `full_diagnostics()['naming_
workspace_activity']` genuinely reflects a real production naming
cycle, including the honest zero-losers shape) — all pass, first run,
no bug found.

Verified: the new script (9 checks); `verify_phase35_w1_naming_
workspace.py`/`verify_e1_explain_cycle.py`/`verify_runtime_invariant.py`
re-run clean (unaffected); `node --check` clean on `app.js`; `pyflakes`
clean on all touched/new files (only the six known pre-existing
forward-ref findings in `engine.py`); a real engine-level check
confirming `full_diagnostics()['naming_workspace_activity']` is
present and correctly empty before any real cycle. No persisted
`World`/`Agent` schema or tick-loop logic changed (`full_diagnostics()`
is a pure read-only diagnostics report) — no replay-hash/native-soak
re-run needed.

## [1.34.242] — Tier 7 HCA Stage E, E1: the "why reasoning was or was not invoked" panel

Explicit user instruction: "Start phase 7 E1."

**E1.** The "why reasoning was or was not invoked" panel — CLAUDE.md's
own Observatory UI direction section had already named the exact line
shape (`IMPASSE(no-change) · "family lines dying out" · 590
occurrences, no rule · DELIBERATED (94s)` / `no impasse · peak
surprise 0.3 < threshold 1.5 · cheap path`). New `hearthmind/cognition/
explain.py`'s `explain_cycle(impasse, outcome=None, deliberation_
seconds=None, no_impasse_detail="")` produces exactly that line — pure
presentation built entirely on C1's real `Impasse` (kind/subject/
detail, verbatim) and C3's real `DispatchOutcome` (`resolved_via`), no
new detection/dispatch mechanism. All three real resolution tiers get
their own honest label (`DELIBERATED (Ns)`/bare `DELIBERATED` when no
elapsed time is supplied/`CHUNK HIT (no deliberation)`/`MODEL
RESOLVED (no deliberation)`); an impasse with no outcome yet correctly
carries no fabricated resolution clause; a no-impasse cycle accepts an
optional caller-supplied `no_impasse_detail`, since `detect_novelty`
(and its siblings) return `None` with no detail on a sub-threshold
reading, and a caller wanting to show WHY must pass the raw signal
itself.

Deliberately no dev-console UI wired this pass, stated up front in the
new module's own docstring: C1/C2/C3 are not wired into any real
production `_schedule_llm_job` call site yet — there is no real
per-cycle `Impasse`/`DispatchOutcome` pair flowing through the live
tick loop for a panel to render today. Same "ship the interface, wire
the first real consumer next" discipline every prior Stage A/B/C/D
item in this codebase has used.

New `scripts/verify_e1_explain_cycle.py` (13 checks — the no-impasse
cheap-path line both bare and with a real supplied detail; a real
no_change impasse with no dispatch outcome yet correctly omitting the
resolution clause; all three real resolution tiers through a real
`ChunkStore`/`dispatch_impasse` cycle incl. the SAME impasse recurring
hitting the real compiled chunk; E1's own stated headline test — a
real 200-cycle mixed soak, every cycle producing a real, legible,
never-malformed one-line reason) — all pass, first run, no bug found.

Verified: the new script (13 checks); `verify_c1_impasse.py`/`verify_
c3_dispatch.py`/`verify_d2_memory_kind.py` re-run clean (unaffected);
`scripts/verify_runtime_invariant.py` re-run clean (the new module
declares no `MEMORY_KIND` — a presentation layer over C1/C3, neither
declarative nor procedural memory, correctly exempt from D2's check
the same way an undeclared module is); `pyflakes` clean on both new
files. No `simulation/engine.py` code path or persisted state touched
— pure offline `cognition/` work, same scope class as C1/C2/C3/D1/D2's
own filings — no replay-hash/native-soak re-run needed.

## [1.34.241] — Tier 7 HCA Stage D, D2: declarative/procedural separation made architectural (Stage D closed in full)

Explicit user instruction: "Start D2."

**D2.** Declarative/procedural separation made architectural — the
doc's own §2.1 (Standard Model of Mind) structural commitment, the
one Tier 7 item with no stated falsifiable test of its own; a real
test was designed for it here, same standing "every item carries a
falsifiable test" discipline. New `hearthmind/cognition/memory_
kind.py`: `MemoryKind` (`DECLARATIVE`/`PROCEDURAL`) + `memory_kind_
of()` — the real single queryable answer this codebase never had
before for "is X a fact an agent knows, or a cached decision about
how to act." `DECLARATIVE_STORE_NAMES` names `Agent`'s real fact-
holding fields (`memories`/`semantic_memories`/`core_memories`/
`beliefs`/`secrets`/`lessons`/`working_memory`); `PROCEDURAL_STORE_
NAMES` names real cached-decision artifact kinds (C2's `ChunkStore`
entries, `TriggerRule`, `CompositeReaction`).

Mechanically enforced by extending `scripts/verify_runtime_
invariant.py` with `check_memory_kind_separation()` — the EXACT
`SPECIALIST_DOMAIN`/`check_domain_write_scope()` shape H1 already
proved for cognitive domains, applied to a different axis: a module
declaring `MEMORY_KIND = MemoryKind.DECLARATIVE` may never import
from `hearthmind.cognition.chunk` (procedural memory's real home),
and a `PROCEDURAL`-marked module may never import from `hearthmind.
agents.agent`/`.activation` (declarative memory's real home). D1's
own `activation.py` now marks itself `DECLARATIVE`; C2's `chunk.py`
marks itself `PROCEDURAL`; C3's `dispatch.py` deliberately declares
NEITHER kind — it's the real neutral composition layer the two
systems meet through by design (imports `chunk` on purpose), exempt
from the check the same way an undeclared/WORLD-domain module was
exempt from H1's own check. The real tree was already clean under
this rule before the check existed — same "formalize/enforce what's
already true" shape B0.1/H1 both used.

New `scripts/verify_d2_memory_kind.py` (13 checks — the type and
classification's own correctness incl. a non-overlap proof; the real
tree confirmed clean; the real `activation.py`/`chunk.py`/`dispatch.
py` markers confirmed directly against the actual files; a synthetic
DECLARATIVE module importing the real procedural store IS caught; a
synthetic PROCEDURAL module importing the real declarative store IS
caught; an unmarked module importing BOTH stores is correctly NOT
flagged; a real end-to-end scan over a synthetic directory finds
exactly the two real violations and nothing else) — all pass, first
run, no bug found.

**This closes Tier 7 HCA Stage D in full** (`D1` v1.34.240, `D2`
here). Stage E (the Cognitive Observatory) is the only remaining
unstarted HCA stage in the roadmap's own dependency-ordered sequence.

Verified: the new script (13 checks); `verify_runtime_invariant.py`
itself re-run clean (zero violations under both its domain check and
this new memory-kind check, over the real full `hearthmind/` tree);
`verify_h1_cognitive_domains.py`/`verify_d1_activation.py`/`verify_
c1_impasse.py`/`verify_c2_chunking.py`/`verify_c3_dispatch.py` re-run
clean (unaffected); `pyflakes` clean on all touched/new files. No
`simulation/engine.py` code path or persisted `World`/`Agent` state
touched — pure offline `cognition/` + verify-script work, same scope
class as C1/C2/C3's own filings — no replay-hash/native-soak re-run
needed.

## [1.34.240] — Tier 7 HCA Stage D, D1: ACT-R memory activation; roadmap stale-docs pass

Explicit user instruction: "Start phase 6 is phase 5 is done with D1
and parallely fix stale docs" — Stage D's own dependency-ordered
sequence names no hard prerequisite, but is placed after Stage C for
narrative continuity in this project's own roadmap.

**D1.** New `hearthmind/cognition/activation.py`: the real ACT-R
base-level activation equation (`ln(Σ_j (t−t_j)^(−d))`, `d≈0.5`,
unifying recency AND frequency into one quantity) plus spreading
activation (salience/relevance/known-causal-tag as three weighted
associative sources), replacing `retrieve_relevant_memories`'s four
hand-tuned `MEMORY_RETRIEVAL_*` weights — all four genuinely
**deleted** from `hearthmind/agents/agent.py`, per D1's own stated
test ("retrieval quality holds... while four constants are deleted").
A real elapsed-tick input needed a genuine new per-memory signal: new
`Agent.memory_ticks` (index-aligned with `memories`, same discipline
as `memory_causes`; a pre-D1 snapshot backfills via `age_ticks` +
`LEGACY_MEMORY_TICK_GAP`, preserving relative recency order as an
honest approximation, never trusted as measured fact). Stamped by
`_remember` from a new module-level `population._CURRENT_TICK` — set
once per real tick by `Population.tick()`'s own top, and mirrored by
`SimulationEngine._tick_once()`'s own top for the handful of `_remember`
call sites living in engine.py's async LLM-job `apply()` closures —
deliberately NOT a `tick` parameter threaded through `_remember`'s own
~46 real call sites, since this exact module already carries the
direct precedent for this shape (`_pending_memory_evictions`: "`_remember`
receives only `agent`, no reference back to Population/World.clock").

Honest scope trim, stated in the new module's own docstring: `Agent`
carries no per-memory rehearsal/access counter today (the HCA doc's
own framing of `memory_access` as an "already exists" input for this
formula was imprecise — that field is real, but scoped to `Pillar`
(B8's reinforce counters), never threaded onto `Agent`) — every memory
here has exactly ONE real presentation, its formation tick;
`base_level_activation` already accepts a real list of presentation
ticks, not just one, so a future `Agent`-side rehearsal counter needs
no signature change. No RNG anywhere in the scoring, matching this
project's own standing arbitration discipline. `retrieve_relevant_
memories` gained an optional `current_tick` param, threaded through
its one real engine-side call site (`_run_personal_belief`); its two
`build_prompt`-side call sites (`llm/cognition.py`, `llm/letters.py`)
are deliberately left at the default (both are pure functions with no
engine access by design) — a real, honest degrade to the newest
memory's own formation tick as "now," not a fabricated fallback.

New `scripts/verify_d1_activation.py` (23 checks — the four deleted
constants confirmed genuinely gone; the real zero-division floor and
same-tick edge case; a genuine frequency proof (two presentations at
the same age activate higher than one — a real capability entirely
absent from the deleted formula); recency still dominating over
stacked-but-old presentations at realistic decay; all three spreading
sources; end-to-end `_remember`/`Agent.memory_ticks` production
wiring; D1's own headline test — a real older high-salience+relevant
memory still outranks three merely-recent mundane ones at a realistic
elapsed-tick gap for a bounded memory list; the `current_tick=None`
production degrade; round-trip + legacy backfill incl. preserved
relative recency order) — all pass. One real test-calibration fix made
before shipping, not a bug in the module under test: the first attempt
used an unrealistic multi-year elapsed-tick gap between the "old"
high-salience memory and three "recent" mundane ones, which correctly
LOST under a faithful single-presentation ACT-R decay (honest model
behavior — a real base-level activation term genuinely decays that
far over that much real elapsed time) — recalibrated to a realistic
gap for a bounded, capped memory list instead of weakening the
formula to fit an unrealistic scenario.

**Roadmap stale-docs pass.** The consolidated Tier 7 checklist's `D1`
entry and Phase 6's own numbered-list `D1` entry both corrected from
`[ ]`/unstarted to real shipped detail; re-swept for any other
stale Stage C references left over from the prior three-commit C1/C2/
C3 sequence — none found, the closing notes were already accurate.

Verified: the new script (23 checks); `verify_c1_impasse.py`/`verify_
c2_chunking.py`/`verify_c3_dispatch.py` re-run clean (unaffected);
`pyflakes` clean on all touched/new files (only the six known
pre-existing forward-ref findings in `engine.py`); `scripts/verify_
replay_hash.py` (800 ticks, seed 777, `--in-process`) — MATCH,
byte-identical; `scripts/verify_native_soak.py` (seeds 1/55, 800
ticks) — MATCH (both required this pass since `Agent`'s own persisted
schema and `simulation/engine.py` both changed). `D2` (declarative/
procedural separation made architectural) is the only remaining open
Stage D item — resume only on future explicit direction.

## [1.34.239] — Tier 7 HCA Stage C, C3: cheap-resolver dispatch (Stage C closed in full); roadmap stale-docs pass

Explicit user instruction: "Start C3 and stale docs."

**C3.** New `hearthmind/cognition/dispatch.py`'s `dispatch_impasse(
impasse, store, tick, llm_resolver, model_resolver=None)`: the real
"cached chunk → learned model → LLM" ladder (HCA §3/Layer 3). C2's
`ChunkStore.lookup()` is tried first (free); an optional caller-
supplied learned-model resolver next; the caller's own genuine
deliberation (`llm_resolver`) only as a real last resort — and ONLY
the LLM tier compiles a new chunk (`ChunkStore.compile`), since a
chunk-hit or model result is already cheap enough that caching it
again buys nothing. `RESOLVED_VIA_KINDS = ("chunk", "model", "llm")`
names the three real tiers, cheapest first.

New `scripts/verify_c3_dispatch.py` (15 checks): the real ladder order
proven directly (a chunk hit never touches model/LLM; a model resolver
never falls through to the LLM; the LLM tier alone compiles a real
chunk, and the SAME impasse recurring afterward hits that chunk
instead of re-deliberating); C3's own stated headline number (">30%
of workspace winners resolve without an LLM call") verified
statistically over a real 2000-cycle recurring-impasse soak (a
realistic distribution — a handful of subjects recur 70% of the time,
the rest are genuinely novel, per HCA's own §1.4 finding) — 70.0%
resolved without an LLM call, well past the stated bar — all pass,
first run, no bug found. Deliberately NOT wired into any real
production `_schedule_llm_job` call site — that retrofit (one
low-risk ambient job first, then a wider sweep) is real, distinct
future work, same "ship the interface, wire the first real consumer
next" discipline C1/C2 already used; a live-production measurement of
the stated >30% bar needs that wiring pass first.

**This closes Tier 7 HCA Stage C in full** (`C1` v1.34.237, `C2`
v1.34.238, `C3` here) — the project's own headline falsification test
(deliberative cost per unit of emergence, trended over a soak) is now
MEASURABLE for the first time, though actually measuring it live
still needs the production wiring pass named above.

**Roadmap stale-docs pass.** The consolidated Tier 7 checklist's `C3`
entry, Phase 5's own numbered-list `C3` entry, and the checklist's
closing "Stages A, B, G, and H... Stage C partially shipped" note
(written for the prior commit, now stale since C3 just closed Stage C
in full) all corrected in the same batch.

Verified: the new script (15 checks); `pyflakes` clean on both new
files. No native module or `simulation/engine.py` code path touched.

## [1.34.238] — Tier 7 HCA Stage C, C2: chunking; further roadmap stale-docs pass

Explicit user instruction: "C2 and stale docs."

**C2.** New `hearthmind/cognition/chunk.py`: `ChunkStore` compiles a
RESOLVED impasse into a cheap reusable artifact so the next occurrence
of the same problem is handled without deliberation, per HCA §3/Layer
4's own text ("a cached decision keyed by the impasse signature, a
Tier 6 model update, a new `TriggerRule`, a revised belief"). `chunk_
signature(impasse)` reduces C1's `Impasse` to `kind`+`subject` —
deliberately NOT `impasse.detail` (which varies run to run even for
the recognizably same problem, e.g. the exact streak count in a
`no_change` impasse) — so two impasses that read as "the same
problem" to a person always collapse to the same chunk. `compile()`
creates a real `Chunk` holding one of HCA's own closed `ARTIFACT_
KINDS` (`cached_decision`/`model_update`/`trigger_rule`/`revised_
belief`, rejecting anything outside that vocabulary); `lookup()` is
the cheap read a future dispatcher (`C3`) would try first; `record_
hit()` is the real reuse signal a future `E4` learning-chart panel
would plot. Bounded (`CHUNK_STORE_MAX=500`), evicting the least-
recently-reused chunk (by `last_hit_tick`, falling back to `created_
tick` for a never-hit chunk) — never the chunk just compiled.

New `scripts/verify_c2_chunking.py` (18 checks, real production data
throughout — a real no-change impasse built from a real `Institution.
objective_ticks_unmet` streak crossing `INSTITUTION_OBJECTIVE_
PERSISTENCE_THRESHOLD` (HCA's own "590 family extinctions, no rule"
worked example) and a real tie impasse from a real arbitrated
`CompetitionRecord`): the same recurring impasse hits the same chunk
regardless of its own varying detail text; a different subject never
cross-hits; an unrecognized `artifact_kind` is rejected; bounded
eviction removes the genuinely least-recently-reused chunk while
protecting both a chunk that was reused and the chunk just compiled —
all pass, first run, no bug found. Deliberately does NOT wire dispatch
(actually consulting `ChunkStore.lookup()` before an LLM call) — C2's
own stated test ("the 591st family extinction consumes no LLM call")
is C2+C3's combined outcome; C3's own "cheap-resolver dispatch" is the
real code path that would call this. No `simulation/engine.py` code
path touched — no replay-hash/native-soak re-run needed.

**Further stale-docs pass.** The same consolidated Tier 7 checklist
still showed `C1` unchecked despite shipping in the prior commit
(v1.34.237) — corrected alongside adding `C2`'s own entry. Phase 5's
own numbered-list entry updated to match. The dependency-ordered
build sequence's closing note (previously corrected to say "Stages A,
B, G, and H are all fully shipped") extended to note Stage C is now
partially shipped (`C1`/`C2`, dispatch `C3` still open) rather than
implying it's entirely untouched.

Verified: the new script (18 checks); `pyflakes` clean on both new
files. No native module or `simulation/engine.py` code path touched.

## [1.34.237] — Tier 7 HCA Stage C, C1: the four typed impasses as the deliberation trigger; roadmap stale-docs pass

Explicit user instruction: "Start C1. And fix stale docs parallely."
Two independent pieces, one batch.

**C1.** New `hearthmind/cognition/impasse.py` (`ImpasseKind`/
`Impasse` + four classifiers) — Soar's four typed impasses (tie,
no-change, conflict, novelty), each classifying an EXISTING real
signal this codebase already maintains rather than inventing a new
detection mechanism: `detect_tie_from_competition` reads a real
`CompetitionRecord` (B1 — every real `GlobalWorkspace.arbitrate()`
cycle already produces one; a tie is the winner scoring within
`TIE_SCORE_TOLERANCE` of the closest real loser); `detect_no_change`
classifies a real caller-supplied streak (e.g. `Institution.
objective_ticks_unmet`) crossing its own real threshold — the HCA
design doc's own worked example, "590 family extinctions, no rule";
`detect_conflict` classifies a real `Pillar.disagrees_with(subject)`
result (B4); `detect_novelty` classifies a real `SurpriseSpecialist.
error()` reading (A1) against the real production `EMERGENCE_
SURPRISE_THRESHOLD`.

New `scripts/verify_c1_impasse.py` (16 checks, every one run against
a REAL production data structure/signal — a real arbitrated
`CompetitionRecord`, a real `Institution`, a real `Pillar`, a real
`SimulationEngine._emergence_surprise` — not a synthetic stand-in) —
all pass, first run, one real test-design issue caught and fixed
before shipping (not a bug in the module under test — an exact-
floating-point tolerance-boundary assertion was brittle against
ordinary float rounding; replaced with two real gaps clearly inside/
outside tolerance). Deliberately scoped to the trigger primitive
alone: C1's own stated test ("every LLM call in a soak carries a
named impasse") describes the end state of `C1`+`C2`+`C3` combined in
production — a real, larger dispatch migration left to `C3`, same
"ship the interface, wire the first real consumer next" discipline
every prior Stage A/B/G/H item here used. No `simulation/engine.py`
code path touched — a pure offline `cognition/` primitive, same scope
class as A1's own `surprise.py` — no replay-hash/native-soak re-run
needed.

**Stale-docs pass.** `docs/ROADMAP-2026-07-REMAINING.md`'s
consolidated Tier 7 checklist (the section that had repeatedly gone
stale before, e.g. the v1.34.229/.222/.212/.202 audits) still showed
`H2`/`H3`/`H4` as unchecked `[ ]` despite all three shipping
(v1.34.235/.236) — corrected with real shipped detail and version
numbers, matching every sibling entry's style. `H1`'s own "flagged as
real future work once `H2`/`H4` give the write-scope enforcement a
real specialist" note updated to reflect that both now exist.
`E6`'s "depends on Stage H" note updated to "now closed, genuinely
unblocked." The checklist's own closing "nothing is implemented" line
(stale — four of eight stages are now fully shipped) corrected to
point at the real per-item `[x]`/`[ ]` state instead of a blanket
claim.

Verified: the new script (16 checks); `pyflakes` clean on both new
files. No native module or `simulation/engine.py` code path touched
by either half of this batch.

## [1.34.236] — Tier 7 HCA Stage H, H4: the Player Model as a real OBSERVER-domain specialist (Stage H closed in full)

Explicit user instruction: "Continue H4" — the last item Stage H
names, independent of H2/H3 (only needed H1's domain type to exist).

New `hearthmind/cognition/player_model.py` (`SPECIALIST_DOMAIN =
Domain.OBSERVER`, zero imports from `hearthmind.world`/`.agents`/
`.settlement`/`.economy`): a real, read-only prediction about the
observer, deliberately distinct from `World.consciousness_player_
model` (the Town Consciousness's own hidden theory about the player,
Phase N — untouched here, since it DOES write real interventions and
stays exactly as it is). `predict_next_focus`/`prediction_error` are
the real `predict()`/`error()` over `World.observer_attention`'s
already-tracked `agent_view_counts` (§4/§5's own existing signal —
which agent has the observer inspected most); `PlayerAttentionModel`
holds the real bounded, measured hit-rate state; `propose_player_
model_bid` is the real `bid()`.

`SimulationEngine` gained a dedicated `self._observer_workspace`
(structurally distinct from `_machine_workspace` and every WORLD-
domain workspace, per "domains never compete for each other's
budget") and `self._player_model`/`self._player_model_history`
(bounded). `_record_observer_attention` (the real `POST /observer/
attention` call site) now computes `predicted = predict_next_focus
(counts)` from the view counts AS THEY STOOD BEFORE the new
observation, updates `World.observer_attention`'s ordinary §4
bookkeeping unchanged, scores the prediction against the real agent
that just arrived, and submits/arbitrates a real `Bid` — the winning
resolver only ever appends to `_player_model_history` for dev-console
display, never touches `hearthmind.world`/`Settlement`/`Agent` state.
Surfaced via `full_diagnostics()['player_model_domain']` (dev-console/
Observatory-only, per "OBSERVER content is dev-console-only by domain
rule").

New `scripts/verify_h4_player_model.py` (27 checks — the module's own
domain marker and the real tree staying clean under `check_domain_
write_scope()`; `predict_next_focus`/`prediction_error` as pure
functions incl. the no-RNG tie-break; `PlayerAttentionModel`'s real
measured hit rate; a solo-bidder `GlobalWorkspace` resolving every
real cycle; `SimulationEngine._observer_workspace`'s real construction
and distinctness from every other workspace; a real first/repeat/
different-agent observation sequence scored correctly (miss/hit/miss);
the H4 headline test — a real before/after `World.to_dict()` diff
(minus the pre-existing `observer_attention` field itself) proves
every other field stays byte-identical; the cross-domain-content AST
proof that `_send_pillar_message` never references `_observer_
workspace`; real `full_diagnostics()` surfacing) — all pass, first
run, no bug found.

**This closes Tier 7 HCA Stage H in full** (H1 v1.34.230, H2+H3
v1.34.235, H4 here) — both the Adaptive Runtime's own scheduling
decisions and the Player Model's own read-only predictions are now
visible in a real workspace log as real bids that won against named
losers.

Verified: the new script (27 checks); `scripts/verify_h2_h3_runtime_
domain.py` (22 checks) re-run clean; `verify_h1_cognitive_domains.py`/
`verify_b1_global_workspace.py`/`verify_b2_starvation_gain.py`/
`verify_b3_pillar_bus.py`/`verify_phase35_w1_naming_workspace.py`
re-run clean; `pyflakes` clean on all touched/new files (only the six
known pre-existing forward-ref findings in `engine.py`); `scripts/
verify_replay_hash.py` (800 ticks, seed 777, `--in-process`) — MATCH,
byte-identical; `scripts/verify_native_soak.py` (seeds 1/55, 800
ticks) — MATCH.

## [1.34.235] — Tier 7 HCA Stage H, H2+H3: the Adaptive Runtime as a real MACHINE-domain specialist family, cross-domain isolation verified

Explicit user instructions, in one batch: "Start H3" / "Start H2" (H2
first, since H3 explicitly depends on it).

**H2.** Four pre-existing Adaptive Runtime modules (`hearthmind.
simulation.escalation`/`.forecasting`/`.profiling`/`.optimization_
hypothesis`) each gained `SPECIALIST_DOMAIN = Domain.MACHINE` — a
real, mechanically-checked claim (`scripts/verify_runtime_
invariant.py`'s `check_domain_write_scope()`, shipped at H1), not a
decorative label; all four already imported nothing from
`hearthmind.world`/`.agents`/`.settlement`/`.economy`, so the tree
stays clean under the new markers. Together they close the honest gap
CLAUDE.md's own HCA section already named: the Adaptive Runtime
already implemented four of L1's five specialist methods under other
names (B8=`predict()`/`error()`, B5=`observe()`, B13=`learn()`) but
had no real `bid()` — B15's `EscalationLadder` unilaterally mutated
engine state with no arbitration, no competition, and no legible
record anywhere a person could watch.

New `hearthmind/cognition/runtime_specialist.py`
(`SPECIALIST_DOMAIN = Domain.MACHINE`, zero world/agent/settlement/
economy imports): `propose_escalation_bid(tick, resolver)` is the
real fix — the ladder's decision becomes a real `Bid` (`specialist_
id="adaptive_runtime"`, `subject="escalation_ladder"`, flat
`score=1.0` since nothing else bids into this workspace yet).
`SimulationEngine` gained a dedicated `self._machine_workspace`
(a `GlobalWorkspace`), deliberately separate from every WORLD-domain
workspace (`_w2_workspaces`/`_w3_workspaces`/`_naming_workspace`/
`_pillar_buses`) per H1's own "domains never compete for each other's
budget" rule. `_maybe_advance_escalation_ladder` no longer mutates
`self._escalation_ladder`/`_cognition_budget` directly — it builds a
resolver closure, submits a bid via `runtime_specialist.propose_
escalation_bid`, arbitrates, and only invokes the winner's resolver.
Provably behavior-preserving by construction: a coalition-of-one
workspace's `arbitrate()` always returns the sole bid, the identical
"ships the interface, wire the first real consumer, prove it's a
no-op today" discipline every W1-W4/H1 site in this codebase already
used. Surfaced via `full_diagnostics()['machine_domain']` (dev-
console/Observatory-only, per H3) — the real cycle count and the
newest winner/losers per cycle.

**Flagged, explicit deviation from H1's own stated rule** ("MACHINE
may write ONLY tunables — see `simulation/tuning.py`'s
`TunableRegistry`"): the winning bid's resolver still mutates
`SimulationEngine._escalation_ladder`/`_cognition_budget` directly,
not a real `TunableRegistry` entry — this subsystem predates H1's
domain framework, and migrating its storage onto a real tunable (so
the rule holds literally, not just in spirit) is real, distinct,
larger future work, not attempted this pass. What IS real and
verified now: the resolver never touches `hearthmind.world`/
`Settlement`/`Agent` state at all — H3's own proof, below.

**H3.** Cross-domain isolation, verified three ways in new `scripts/
verify_h2_h3_runtime_domain.py`: (1) a real before/after
`World.to_dict()` diff around a forced-pressured `_maybe_advance_
escalation_ladder()` call (backpressure limit/backlog monkeypatched
to force `pressured=True`) proves ZERO world-state change — only
engine-level `_escalation_ladder`/`_cognition_budget` moves; (2)
`self._machine_workspace` is confirmed structurally distinct (never
the same object, never a value inside) from every WORLD-domain
workspace container; (3) an AST scan of `_send_pillar_message` (the
real WORLD-domain messaging arrow) confirms it never references
`_machine_workspace` — a MACHINE bid genuinely cannot flow into a
settlement's own belief formation, "cross-domain content flows only
through L5" holding as more than a stated rule.

New `scripts/verify_h2_h3_runtime_domain.py` (22 checks — all five
modules' real `SPECIALIST_DOMAIN` markers; the real tree stays clean
under `check_domain_write_scope()`; `propose_escalation_bid`'s own
contract; a solo-bidder `GlobalWorkspace` resolving every real cycle,
same provably-behavior-preserving proof every W1-W4 site already
used; `SimulationEngine._machine_workspace`'s real construction and
distinctness from every WORLD-domain workspace; a real `day_end` call
genuinely advancing the machine workspace's cycle counter and
recording a real winner; a non-`day_end` call as a genuine no-op; the
H3 world-state-isolation proof under real forced pressure; the
cross-domain-content AST proof; `full_diagnostics()` surfacing real
`machine_domain` state) — all pass, first run, no bug found in the
module under test.

Verified: the new script (22 checks); `verify_b1_global_workspace.py`
through `verify_b7_learned_bidding.py`, `verify_phase35_w1_naming_
workspace.py`, `verify_h1_cognitive_domains.py`, `verify_w2_batch1_
narrative_jobs.py`, `verify_w2_batch2_full_sweep.py`, `verify_w3_
settlement_scoped_workspaces.py`, `verify_w4_pillar_bus_migration.py`
re-run clean; `pyflakes` clean on all touched/new files (only the six
known pre-existing forward-ref findings in `engine.py`); `scripts/
verify_replay_hash.py` (800 ticks, seed 777, `--in-process`) — MATCH,
byte-identical; `scripts/verify_native_soak.py` (seeds 1/55, 800
ticks) — MATCH. `H4` (the Player Model as an OBSERVER-domain
specialist, independent of H2/H3) is the last open Stage H item —
resume only on future explicit direction.

## [1.34.234] — Phase 3.5 W4: `_send_pillar_message` migrated onto real `PillarBus` subscriptions (Phase 3.5 closed in full)

Explicit user instruction: "Complete W4."

Migrates `SimulationEngine._send_pillar_message`'s 26 real call sites
(B3's own count, "~29") off a hand-wired direct `Pillar.send_message`/
`receive_message` call pair onto real `PillarBus` subscriptions —
already shipped and verified at B3 (v1.34.225), but never given a
real production consumer until now.

New `SimulationEngine._pillar_bus_for(to_name)`: one dedicated
`PillarBus` per RECEIVING pillar name (`self._pillar_buses`), lazily
created and subscribed exactly once with a genuinely sender-agnostic
handler (no branch on `bid.specialist_id`) — a NEW sender reaching an
EXISTING receiver needs zero new wiring, the real generalization
`PillarBus` itself already promised.

`Bid` (`hearthmind/cognition/workspace.py`) gained two additive
fields, `message_kind: str | None = None` and `message_data: dict |
None = None`, so the bus can carry a message's real typed `kind`
(`cognition.pillar.MESSAGE_KINDS`) through to the receiving handler —
`_pillar_observe_turn`'s salience ranking has no other way to read it
off a bare `Bid`. Every other bid family (every W1-W3 site, A1's
`SurpriseSpecialist`, every `scripts/verify_b*` fixture) leaves both
fields at their default `None`, reproducing identical behavior — same
"additive field, zero call-site changes needed" precedent `domain`
(H1) already set.

`_send_pillar_message`'s own 26 real call sites needed ZERO edits —
only the method's internal body changed: it still builds and records
the sender's own `outbox` entry exactly as before (unchanged shape),
then submits a real `Bid` to the recipient's dedicated bus and calls
`publish_cycle()` instead of calling `receive_message()` directly.

Deliberately POINT-TO-POINT delivery (one bus, one real subscriber,
provably a coalition of one every cycle) — NOT the fuller genuine
broadcast-to-every-subscribed-pillar design `PillarBus` itself already
supports and B3's own test already proved (multi-subscriber
broadcast). Flagged as real, distinct, larger future work: it would be
a genuine simulation-behavior change (today's one specific recipient
becoming several) this offline environment has no live world to
verify the consequence against, the same caution `_w3_workspaces`'s
own deferred batched-arbitration extension already gives.

New `scripts/verify_w4_pillar_bus_migration.py`: a structural AST
proof that all 26 real call sites are unchanged and no direct
`.receive_message(` call remains outside the bus handler; the shared
helper's own contract (lazy per-receiver bus, exactly one subscriber,
no duplicate subscription on repeat calls); direct delivery proof
(sender's outbox unchanged in shape, recipient's inbox receives the
real kind/summary/data intact, an unsubscribed pillar receives
nothing — point-to-point, not broadcast); a real production call site
(innovation→village discovery, `_maybe_schedule_ontology_proposal`)
through a fake `LLMAdapter`; a real 8000-tick LLM-disabled production
soak confirming real inter-pillar traffic flows organically through
the new mechanism with a real winner every cycle — all pass, first
run, no bug found.

**This closes Phase 3.5 in full** (W1 v1.34.230, W2 v1.34.231/.232,
W3 v1.34.233, W4 here) — every one of the roadmap's original W1-W4
items is now genuinely wired into the live simulation.

Verified: the new script; `verify_b1_global_workspace.py` through
`verify_b7_learned_bidding.py`, `verify_phase35_w1_naming_workspace.py`,
`verify_h1_cognitive_domains.py`, `verify_w2_batch1_narrative_jobs.py`,
`verify_w2_batch2_full_sweep.py`, `verify_w3_settlement_scoped_
workspaces.py` re-run clean; `pyflakes` clean on both touched files
(only the six known pre-existing forward-ref findings in `engine.py`);
`scripts/verify_replay_hash.py` (800 ticks, seed 777, `--in-process`)
— MATCH; `scripts/verify_native_soak.py` (seeds 1/55, 800 ticks) —
MATCH (both required — `simulation/engine.py` changed).

## [1.34.233] — Phase 3.5 W3: settlement-scoped granularity for per-agent traffic, plus a roadmap correction and W4

Explicit user instruction: "Fix the roadmap's stale '~78+~29' framing
and start W3. Also add these 29 arrows as W4 if not already done.
Complete W3 in one run."

**Roadmap correction.** Phase 3.5's original phase-sequence text
guessed at W2's scope with a "~78+~29" figure before anyone had
actually enumerated the real target — it conflated two unrelated,
larger categories: "~78" was A2's own count of `_append_emergence`-
adjacent sites (anywhere code touches the emergence log, far broader
than LLM scheduling); "~29" was `_send_pillar_message` arrows (the
older point-to-point pillar-messaging mechanism, structurally
unrelated to LLM job scheduling). The real, AST-verified total (see
v1.34.232) was 54 `_schedule_llm_job` call sites — 46 converted, 8
deliberately excluded. Corrected in place; the "~29" figure is now
split out as its own item, `W4`, below.

**W3, shipped.** Settlement-scoped `GlobalWorkspace` granularity for
the three real per-agent/per-pair call sites W2 deliberately left
alone: `rumor_interpret` (a core-cast listener retelling a heard
rumor), `personal_belief` (a monthly Reflect() pick revising a private
belief), `mind` (one-time permanent-identity authoring for a newly-
seated core-cast agent) — the largest single remaining share of real
LLM volume.

New shared `SimulationEngine._submit_and_resolve_settlement(
settlement_id, job_name, subject, resolver)`: the settlement-scoped
sibling of W2's `_submit_and_resolve`, keyed by `self._w3_workspaces
[settlement_id]` instead of by job name — so a rumor-interpretation
bid and a personal-belief bid for the SAME settlement genuinely land
in the same arbitration pool, rather than three permanently-separate
per-job-name pools the way W2's sites work. This is the real
structural difference the item's own original text asked for: "one
`GlobalWorkspace` per settlement... competing agents within a
settlement genuinely arbitrate against each other."

Deliberately submit-then-immediately-arbitrate at each call site, the
same coalition-of-one-per-call shape every W1/W2 site already uses —
NOT a batched cross-call-type arbitration pass. A genuinely batched
design (collecting bids from all three job types across a tick before
one shared arbitration pass per settlement) would mean a real
candidate this tick can lose to a same-settlement rival and simply not
fire at all, a materially different simulation-behavior change this
pass deliberately does not risk making without a live world to verify
the consequence against. Flagged as real, distinct future work.

New `scripts/verify_w3_settlement_scoped_workspaces.py`: the shared
helper's own contract, direct; a structural proof that two DIFFERENT
job names for the SAME settlement share the literal same workspace
object while the SAME job name for two DIFFERENT settlements lands in
two DIFFERENT objects; each of the three real sites' own arbitration
cycle through the real production apply path with a fake `LLMAdapter`;
a real 8000-tick LLM-disabled production soak confirming multiple job
types fire organically with a real winner every cycle — all pass,
first run except two real test-setup fixes (a `parse_interpretation`
field-name mismatch in the test's own fake answer; a soak-loop break
condition that stopped on ANY workspace history entry instead of the
specific job type being awaited), no bug found in the module under
test.

**W4 added**, not started: B3's ~29 `_send_pillar_message` arrows
(the older point-to-point pillar-messaging mechanism, `Pillar.send_
message`/`receive_message`, v1.9.0) onto real `PillarBus`
subscriptions — structurally distinct from W1-W3, which all migrate a
LLM SCHEDULING decision; W4 migrates an already-decided-content
INTER-PILLAR MESSAGING arrow onto the same bus mechanism for a
different reason.

Verified: the new script; `verify_b1_global_workspace.py` through
`verify_b7_learned_bidding.py`, `verify_phase35_w1_naming_workspace.py`,
`verify_h1_cognitive_domains.py`, `verify_w2_batch1_narrative_jobs.py`,
`verify_w2_batch2_full_sweep.py` re-run clean; `pyflakes` clean on
both touched files (only the six known pre-existing forward-ref
findings in `engine.py`); `scripts/verify_replay_hash.py` (800 ticks,
seed 777, `--in-process`) — MATCH; `scripts/verify_native_soak.py`
(seeds 1/55, 800 ticks) — MATCH (both required — `simulation/engine.py`
changed).

## [1.34.232] — Phase 3.5 W2, batch 2: the real sweep, all at once

Explicit user follow-up: "Can't you build many sites in one run?
Otherwise this will take ages like tier 0" — a direct instruction to
apply the project's own standing "never migrate one at a time" rule to
W2's remaining sweep, after batch 1 (v1.34.231) deliberately proved the
`_submit_and_resolve` pattern on just four sites first.

**Batch 2, 42 real call sites, one AST-driven bulk transform.** A
Python `ast`-based script located every remaining `self._schedule_llm_
job(...)` call in `simulation/engine.py`, classified it, and rewrote it
as `self._submit_and_resolve("job_name", subject, lambda: self.
_schedule_llm_job(...))` — the exact shared-helper pattern batch 1
established, with every original call's arguments/kwargs preserved
verbatim. Converted: `chronicle`, `tradition`, `folklore`, `legend`,
`invention`, `ontology_proposal`, `ontology_evolution`, `composite_
entity`, `nature_mind`, `species_variant`, `rule_propose`, `composite_
reaction_propose`, `era_branch`, `festival`, `religion`, `narrative_
direction`, `culture_digest`, `institution_culture`, `consciousness`,
`reflection_question`, `reflection`, `self_tuning_advisory`, `self_
tuning`, `caravan`, `town_brain`, `beliefs`, `dream`, `memory_drift`,
`skill_mastery`, `nature_causal_reasoning` (three distinct subjects —
predator extinction, grazer extinction, succession stall — sharing one
workspace, since it's genuinely one job with three trigger paths, not
three jobs), `dispute`, `faction`, `guild_founding`, `institution_
belief`, `diplomacy`, `laws`, `noncore_nudge`, `letter`, `fission`,
`migration_decision`.

**This closes W2 down to exactly the sites that were never meant to
convert.** `naming` already routes through its own dedicated `_naming_
workspace` (W1's pilot — functionally identical mechanism, a different
attribute name, correctly untouched). `rumor_interpret`/`personal_
belief`/`mind` are real per-agent/per-pair call sites — W3's own
territory, a distinct settlement-scoped-`GlobalWorkspace`-granularity
design decision the roadmap explicitly defers, deliberately not forced
into this batch. `sim_summary`/`chronicler`/`pillar_chat_*`/`away_
digest` are real user-triggered on-demand jobs (an explicit player
action, not a periodic cadence a workspace should arbitrate over) —
same reasoning that excluded `sim_summary`/`away_digest` from batch 1,
extended to the two more sites of this same shape found this pass.

New `scripts/verify_w2_batch2_full_sweep.py`: a structural AST proof
over the real source file (not merely asserted) confirms this is the
COMPLETE convertible set — exactly 46 real `_submit_and_resolve` call
sites total (4 from batch 1 + 42 here), each verified to wrap a real
`_schedule_llm_job` call inside a real lambda, and exactly 8 real
un-wrapped `_schedule_llm_job` calls remaining, every one matching the
deliberate-exclusion list above, none unaccounted for — plus
representative functional checks (`town_brain`/`dream` each driven to
their own real staggered monthly day via genuine `_tick_once()` calls;
the shared-workspace multi-subject `nature_causal_reasoning` trio;
`letter`'s real monthly gate) and a real 8000-tick LLM-disabled
production soak confirming 12 distinct newly-converted jobs fire
organically with a real winner on every single arbitration cycle,
proving the shared-per-job-name-workspace mechanism scales cleanly
across this many job names with zero cross-contamination — all pass,
first run except two real test-setup fixes (the synthetic engine's
`agents` field is a list, not a dict; `_monthly_gate` needs the job's
own real staggered day-of-month, reached by ticking the real engine
forward rather than trying to set the derived `day_of_month` property
directly), no bug found in the module under test.

Verified: the new script; `verify_b1_global_workspace.py` through
`verify_b7_learned_bidding.py`, `verify_phase35_w1_naming_workspace.py`,
`verify_h1_cognitive_domains.py`, `verify_w2_batch1_narrative_jobs.py`
re-run clean; `pyflakes` clean on both touched files (only the six
known pre-existing forward-ref findings in `engine.py`); `scripts/
verify_replay_hash.py` (800 ticks, seed 777, `--in-process`) — MATCH;
`scripts/verify_native_soak.py` (seeds 1/55, 800 ticks) — MATCH (both
required — `simulation/engine.py` changed extensively this pass).
Remaining open: `W3` (settlement-scoped `GlobalWorkspace` granularity
for the three real per-agent/per-pair sites named above) is the only
real work left in Phase 3.5 — resume only on future explicit direction.

## [1.34.231] — Phase 3.5 W2, batch 1: the real sweep begins

Explicit user instruction: "W2." The real sweep of remaining
`_schedule_llm_job` call sites onto Stage B's workspace, now that W1's
pilot has proven the pattern is genuinely behavior-preserving.

New shared `SimulationEngine._submit_and_resolve(job_name, subject,
resolver)` helper factors W1's own submit/arbitrate/resolve pattern
out of `_naming_workspace`'s bespoke one-off shape, so each new
migrated call site becomes a one-line wrap rather than duplicating that
boilerplate at every new site. `self._w2_workspaces` lazily creates one
dedicated `GlobalWorkspace` per job name — nothing else ever submits to
a given job's workspace, so every real cycle stays a genuine "coalition
of one," the same provably-behavior-preserving reasoning `_naming_
workspace`'s own docstring already gives in full.

**Batch 1, four real call sites:** `documentary` (year-end narration),
`musing` (daily Reflection voice), `omen` (rare ambiguous flavor
event), `record` (a departed villager's written artifact — the one
PER-CANDIDATE loop in this batch, converted with the same "multiple
independent cycles within one call" shape as W1's own multi-settlement
naming case, proving the pattern generalizes beyond a single-entity
call). Deliberately excluded from this batch: `sim_summary`/`away_
digest` — both user-triggered (`POST /summary/request`/`POST /digest/
request`) with their own docstrings explicitly reasoning about NOT
being part of the coincident monthly job cluster the backpressure gate
exists to smooth; migrating those needs its own real judgment call
about whether arbitration changes that reasoning, not rushed into this
batch alongside four unrelated ambient jobs.

New `scripts/verify_w2_batch1_narrative_jobs.py` (12 checks — the
shared helper's own contract proven directly first: a resolver fires
on a real coalition-of-one win, and two different job names genuinely
get separate dedicated workspaces; each of the four real sites' own
arbitration cycle runs correctly through the real production code
path with a minimal fake `LLMAdapter` standing in for a live server;
`record`'s per-candidate loop produces two independent arbitration
cycles for two real candidates submitted within one call, each naming
the correct per-author subject; `omen`'s real `phase_g_intensity=0.0`
early-out correctly never touches the workspace at all) — all pass,
first run, no bug found.

Verified: the new script (12 checks); `verify_b1_global_workspace.py`
through `verify_b7_learned_bidding.py`, `verify_phase35_w1_naming_
workspace.py`, `verify_h1_cognitive_domains.py` re-run clean;
`pyflakes` clean on all touched/new files (only the six known
pre-existing forward-ref findings in `engine.py`); `scripts/verify_
replay_hash.py` (800 ticks, seed 777, `--in-process`) — MATCH,
byte-identical; `scripts/verify_native_soak.py` (seeds 1/55, 800
ticks) — MATCH (both required this pass since `simulation/engine.py`
itself changed again). Remaining: ~74 more `_append_emergence`-
adjacent + ~29 `_send_pillar_message` arrows, in further W2 batches —
never one at a time, never all at once. `W3` (settlement-scoped
granularity for per-agent cognition/dialogue traffic, the largest real
LLM-volume share) stays gated on W2 progressing further.

## [1.34.230] — Phase 3.5 W1 (real production wiring pilot) + HCA Stage H's H1 (cognitive domains)

Explicit user instruction: "Start phase 3.5 W1 and a parallel task of
your choice with biggest impact." Two independent pieces, one batch.

**W1.** The real production pilot for wiring Stage B's `GlobalWorkspace`
into a live LLM call site — closing the gap every prior Phase 3 filing
named honestly ("no LLM call site is a bid"). `SimulationEngine._maybe_
schedule_naming` now `submit()`s a real `Bid` to a dedicated `self.
_naming_workspace` per eligible settlement and calls `arbitrate()`
immediately after, invoking the winning bid's own `resolver` (the real
`_schedule_llm_job` call) only when `arbitrate()` returns a winner —
same "small, self-contained, no cross-job coupling" selection B0.3's
own first migration (`_maybe_schedule_naming` itself) already used.
Provably behavior-preserving by construction: this workspace has no
other bidder, so every real cycle is a genuine "coalition of one"
(`Bid.score=1.0`, `arbitrate()`'s own `max()` always returns the sole
bid).

Verified via `scripts/verify_replay_hash.py` (LLM-disabled — the code
path is correctly unreached, since the early-out `if not self._
cognition_runner.enabled: return` still gates the whole workspace
call, confirmed byte-identical) and new `scripts/verify_phase35_w1_
naming_workspace.py` (11 checks, a minimal fake `LLMAdapter` standing
in for a live server — a real arbitration cycle genuinely runs and
logs a `CompetitionRecord`, the winning bid's `resolver` is what
actually fires the LLM job (not a bypass), the end-to-end outcome
matches the pre-W1 unconditional-call behavior exactly, and two
settlements eligible in the SAME call each get their own independent
arbitration cycle rather than one suppressing the other) — all pass,
first run, no bug found.

**Parallel task: HCA Stage H's H1**, chosen as the highest-impact
available slice — the first item this session's own Stage B (v1.34.229)
+ Stage G (v1.34.219) closures genuinely unblock. Cognitive domains as
a real, mechanically-enforced type. New `hearthmind.cognition.
workspace.Domain` (`WORLD`/`MACHINE`/`OBSERVER`) + `Bid.domain`
(defaults to `WORLD`, reproducing every prior/existing bid's behavior
with zero call-site changes — W1's own naming pilot needed no edits).
`scripts/verify_runtime_invariant.py` gained `check_domain_write_
scope()`: a module declaring itself MACHINE/OBSERVER-domain via a
`SPECIALIST_DOMAIN = Domain.<X>` module-level marker may never import
from `hearthmind.world`/`.agents`/`.settlement`/`.economy` — the same
"zero import, not just zero write" scope-isolation discipline `verify_
hearthbench_isolation.py` already established for a structurally
identical problem, scanned over the WHOLE `hearthmind/` tree (a
MACHINE/OBSERVER module is expected to live outside `GOVERNED_DIRS`).

New `scripts/verify_h1_cognitive_domains.py` (10 checks — the real
tree is clean today, since no MACHINE/OBSERVER-domain module exists in
production yet (`H2`/`H4`'s later job); a synthetic MACHINE-domain
file importing real world state IS caught; a synthetic OBSERVER-domain
file importing real agent state IS caught; the identical import under
a WORLD-domain marker, or no marker at all, is correctly NOT flagged;
a real arbitration cycle preserves a bid's own domain unchanged) — all
pass, first run, no bug found. Marked "partial" in the roadmap:
per-domain BUDGETS (H1's other named half) aren't built yet — no real
MACHINE/OBSERVER specialist exists to need one; real future work once
`H2`/`H4` give the write-scope enforcement something to actually
govern.

Verified: both new scripts; `verify_b1_global_workspace.py`/`verify_
b2_starvation_gain.py`/`verify_b3_pillar_bus.py`/`verify_b4_coalition_
formation.py`/`verify_b5_evidence_scoring.py`/`verify_b6_arbitration_
determinism.py`/`verify_b7_learned_bidding.py` re-run clean; `pyflakes`
clean on all touched/new files (only the six known pre-existing
forward-ref findings in `engine.py`); `scripts/verify_replay_hash.py`
(800 ticks, seed 777, `--in-process`) — MATCH, byte-identical;
`scripts/verify_native_soak.py` (seeds 1/55, 800 ticks) — MATCH (both
required this pass since `simulation/engine.py` itself changed).

## [1.34.229] — HCA Stage B closes in full (B7), plus a roadmap-status audit

Explicit user instruction: "Start B7 and a parallel task." Two
independent pieces, one batch — **this closes Tier 7 HCA Stage B in
full** (B1-B7 all shipped).

**B7.** Learning to bid from realised outcomes — the roadmap's own
"did the broadcast reduce anyone's subsequent prediction error? did
real emergence follow? was a chunk produced? credited back to winning
coalitions and, where a counterfactual is honestly available, to
losing ones." New `hearthmind/cognition/workspace.py`'s `OutcomeLearner`
(a real, bounded per-specialist running mean of measured `[0,1]`
outcomes, `OUTCOME_EMA_RATE`, remapped onto `[HISTORICAL_USEFULNESS_
FLOOR, HISTORICAL_USEFULNESS_CEILING]`) plus `credit_winning_coalition`
(credits every genuinely independent member of B4's own `Coalition`
with the same measured outcome) and `credit_losing_bid` (credits a
losing specialist ONLY from a real caller-supplied counterfactual,
never a guessed one). Feeds directly into B5's own already-real
`BidFactors.historical_usefulness` multiplicative slot — B5's own
docstring had named this precise gap ("LEARNING what value it should
hold from realised outcomes is explicitly B7's job"). Deliberately the
smallest real thing that makes B7 true: reuses Stage G's own "revise a
bounded scalar from real evidence, never guess" ontogeny shape rather
than a full trained model, since the one number B5 needs is a scalar.

Both of the HCA amendment's named guardrails hold by construction, not
convention: `OutcomeLearner` holds no reference to `GlobalWorkspace` at
all (structurally incapable of touching staleness gain, up or down);
`credit()` only ever accepts a real caller-supplied outcome value.

New `scripts/verify_b7_learned_bidding.py` (13 checks — the roadmap's
own stated headline test, a deliberately-favored-at-first "unreliable"
specialist and an initially-behind "reliable" one, given otherwise
IDENTICAL raw `BidFactors`, genuinely INVERT rank order after a real
run of credited outcomes; a chronically-losing specialist's real
`GlobalWorkspace` staleness count proven IDENTICAL whether or not an
independent `OutcomeLearner` is simultaneously active crediting other
specialists in the same run; `credit_winning_coalition`'s real dedup
behavior against a duplicate-source coalition member; `credit_losing_
bid`'s real counterfactual path; end-to-end proof that a learned gain
genuinely raises a real `evidence_bid`'s own score) — all pass, first
run, no bug found.

**Parallel task: a real roadmap-status audit, closing a documentation
gap left across the last several turns.** Every B1-B6 turn this
session correctly shipped its own detailed checklist entry, but the
Phase 3 sequence's own short summary list (`docs/ROADMAP-2026-07-
REMAINING.md`'s "1. `B1` — PARTIAL, v1.34.223... 2. `B2`... 7. `B7`")
had been left with its original stale one-line descriptions the whole
way through — `B1` still read "PARTIAL" despite shipping in full, and
none of `B2`-`B6` carried their own real ship version. Corrected all
seven entries with their real `SHIPPED, vX.Y.Z` status, and marked the
section header itself "CLOSED IN FULL, v1.34.229" — closing a real,
accumulated documentation-accuracy gap rather than leaving it for a
future audit to rediscover, the same class of finding as v1.34.228's
`aesthetics.py` note.

Verified: the new script (13 checks); `verify_b1_global_workspace.py`/
`verify_b2_starvation_gain.py`/`verify_b3_pillar_bus.py`/`verify_b4_
coalition_formation.py`/`verify_b5_evidence_scoring.py`/`verify_b6_
arbitration_determinism.py` re-run clean; `pyflakes` clean on all
touched/new files. No native module or `simulation/engine.py` code
path touched — no replay-hash/native-soak re-run needed. Phase 3.5
(`W1`-`W3`, the real production wiring) and `H1` (needs Stage B + Stage
G, both now closed) are both genuinely unblocked — resume either only
on future explicit direction.

## [1.34.228] — HCA Stage B's B6, plus a C++-porting-backlog audit finding

Explicit user instruction: "Start B6 and complete something from the
parallel tasks too." Two independent pieces, one batch.

**B6.** Arbitration determinism and the starvation bound. Two of the
item's three named claims (identical evidence produces an identical
winner; no RNG anywhere in arbitration) were already TRUE by
construction since B1/B2 — no code change was needed for those two,
only mechanical proof rather than trusting prose. New `staleness_win_
bound(weak_score, strong_score)` (`hearthmind/cognition/workspace.py`)
makes the starvation guarantee a real closed-form formula: the exact
minimum consecutive-loss count `k` at which a chronically-losing bid's
staleness-gained score first strictly exceeds a rival's real score,
solving B2's own gain formula directly rather than leaving "eventually
wins" as an informal claim.

New `scripts/verify_b6_arbitration_determinism.py` (8 checks — a real
cross-process hash comparison over a deterministic 60-cycle bid
sequence, `verify_replay_hash.py`'s own subprocess-isolation technique
applied to the workspace; a real AST scan for banned RNG imports,
proven to genuinely catch a synthetic violation and not merely pass on
already-clean code; `staleness_win_bound()`'s own predicted loss count
matched EXACTLY where a real `GlobalWorkspace` simulation wins, across
five real score ratios, not just the one 9x example B2's own test
used; a genuine lower-bound proof — the weak bid never wins any cycle
before its predicted bound; both edge cases — already-winning/tied
returns 0, a non-positive `weak_score` raises rather than lying about
a finite bound) — all pass. One real test-design bug caught and fixed
before shipping, not a bug in the module under test: the first draft
compared the formula's own loss-count directly against a cycle number
and let `weak` submit first, which let an exact-tie boundary case win
one cycle early via tie-break rather than a genuine strict win — fixed
by always submitting `strong` first (removing tie-break-order
ambiguity entirely) and comparing against `bound + 1` (staleness
applied on cycle `c` reflects `c - 1` PRIOR losses, so the real win
lands one cycle after the loss count itself).

**Parallel task: a real C++-porting-backlog documentation gap found
and closed.** Audited `world/aesthetics.py`'s `tick_aesthetic_votes`
(the beauty-field per-agent voting mechanic, shipped v1.34.74, after
R7's "new physical-substrate code is C++-first" mandate took effect)
and found it carried no R7-deviation note at all — unlike its sibling
`world/minerals.py`, which documents the identical low-density
reasoning explicitly. Confirmed the omission was a real gap, not a
silent violation: `BEAUTY_APPRAISAL_CHANCE_PER_TICK=0.02` keeps the
real per-tick vote count roughly constant (~1 vote/tick at a 50-agent
settlement) REGARDLESS of population size — the opposite shape from
every already-ported per-tick module in `cpp/src/` (needs/emotion/
relationship step, farm/wildlife/settlement ticks), each of which
scales with population or grid size and therefore has real throughput
to reclaim from a native port. A flat, population-independent low-
frequency roll has no such throughput to reclaim, matching `minerals.
py`'s own documented precedent exactly. Closed the gap by adding the
same explicit R7-deviation note to `aesthetics.py`'s module docstring
— a native port stays a reasonable future follow-up, not attempted
this pass, now documented rather than silently absent.

Verified: the new script (8 checks); `verify_b1_global_workspace.py`/
`verify_b2_starvation_gain.py`/`verify_b3_pillar_bus.py`/`verify_b4_
coalition_formation.py`/`verify_b5_evidence_scoring.py` re-run clean;
`pyflakes` clean on all touched/new files. No native module or
`simulation/engine.py` code path touched — no replay-hash/native-soak
re-run needed. `B7` (learning to bid from realised outcomes, needs
Stage G) is the next open Stage B item — resume only on future
explicit direction.

## [1.34.227] — Roadmap: schedule Stage B's production wiring (Phase 3.5), plus HCA Stage B's B5

Explicit user follow-up to a direct question ("Will all B items wire
to the production once we finish this phase?"): the honest answer was
no — nothing in the roadmap had ever scheduled the actual migration of
real LLM call sites onto Stage B's workspace, only named it as "real,
separate future work" inside B1's own entry. User instruction: "add it
and update the roadmap accordingly and start B5." Two independent
pieces, one batch.

**Roadmap addition (docs-only).** New "Phase 3.5 — Wire Stage B's
workspace into production" (`docs/ROADMAP-2026-07-REMAINING.md`),
sequenced right after Stage B closes in full (`B7`) rather than
starting mid-stage — B5's real scoring and B7's learned bid gains both
change how a bid's score is computed, so wiring real call sites
against an interim formula that's about to change twice would mean
re-touching every migrated site multiple times. Three real steps:
`W1` (a single low-risk pilot call site, same shape as B0.3's own
first real subsystem migration), `W2` (the real sweep of ~78
`_append_emergence`-adjacent + ~29 `_send_pillar_message` sites, in
batches, never one at a time and never all at once), `W3` (settlement-
scoped `GlobalWorkspace` granularity for per-agent traffic, per §3.1's
own "one serial channel per domain" nesting). Its test is B1's own
originally-stated one, finally scheduled to be attempted for real:
"pillar-level call share rises from 1.4% to > 15% without raising
total calls."

**B5.** New `BidFactors`/`compute_evidence_score`/`evidence_bid`
(`hearthmind/cognition/workspace.py`): six of the roadmap's own seven
named factors (surprise, consequence, confidence, urgency, uncertainty,
historical usefulness) as a real formula -- the four base factors
average to `[0, 1]`, `historical_usefulness` applies as a genuine
multiplicative gain (halving it exactly halves the gained score, never
an addend), the `uncertainty` exploration bonus adds `+beta*sqrt
(uncertainty)` on top (UCB-style, Auer et al. 2002). Staleness, the
seventh factor, is deliberately not reproduced -- `GlobalWorkspace`
already tracks and applies it (B2) at comparison time. `provenance` is
a real per-factor audit field for the future Observatory "why did this
win" panel (E1/E2).

New `scripts/verify_b5_evidence_scoring.py` (13 checks -- the roadmap's
own stated test: with expected value (base factors) held exactly
equal, the higher-uncertainty coalition scores higher, the direct
proof exploration is real and not randomness; exact formula match by
hand; the multiplicative-gain proof both directions; out-of-range
clamping incl. a negative gain never flipping a bid's sign; provenance
preservation; a real end-to-end integration through the unmodified
`GlobalWorkspace`) -- all pass, first run, no bug found.

Verified: the new script (13 checks); `verify_b1_global_workspace.py`/
`verify_b2_starvation_gain.py`/`verify_b3_pillar_bus.py`/`verify_b4_
coalition_formation.py` re-run clean; `pyflakes` clean; a full sweep of
`scripts/verify_*.py` found zero regressions. No native module or
`simulation/engine.py` code path touched this pass -- no replay-hash/
native-soak re-run needed.

## [1.34.226] — HCA Stage B, B4: coalition formation, plus E5's learning-curve panel

Explicit user instruction: "Start B4 and build something from parallel
list as well." Two independent pieces, one batch.

**B4.** New `Coalition`/`form_coalitions`/`merged_coalition_score`
(`hearthmind/cognition/workspace.py`): bids naming the same `subject`
merge via noisy-OR (`1 - product(1 - s_i)`) over only the genuinely
independent subset -- new `Bid.evidence_source` field lets two bids
grounded in the exact same underlying reading collapse to just the
higher-scoring one ("two views of one underlying reading are one
bidder, not two"), falling back to `specialist_id` when unset. Noisy-OR
is superadditive (real independent corroboration raises the combined
score above any single reading alone) but sublinear/saturating (bounded
strictly by 1.0 regardless of term count, so a pile of weak evidence
has a hard ceiling a single strong reading can still clear). Doesn't
change `GlobalWorkspace.arbitrate()`'s own comparison this pass -- B1's
own docstring already named step 3 (scoring) as B5's job, so `form_
coalitions` ships as the standalone mechanism B5 will consume, not
wired in yet.

New `scripts/verify_b4_coalition_formation.py` (16 checks -- the
roadmap's own stated test, both thresholds computed and confirmed by
hand before writing the assertion: five independent mild (0.35)
corroborating bids (merged 0.884) beat one strong isolated (0.85) bid;
ten weak (0.1) bids (merged 0.651) still lose to one genuine crisis
(0.95) reading; exact formula match; a lone bid reproduces its own raw
score; shared-evidence_source dedup proven both ways (collapses AND
that the collapse is load-bearing vs. the genuinely-independent case);
mixed-subject grouping; empty-input safety; the saturation bound
genuinely approached with many strong bids; deterministic ordering) --
all pass, first run, no bug found.

**Parallel list item, chosen for genuine buildability: HCA Stage E's
E5** ("per-specialist learning curves: live prediction-error-over-time,
one line per specialist, with G3's regime-change re-adaptation visibly
plotted"), one of the roadmap's own explicitly-flagged "ship right
after Phase 1 closes, don't wait for anything later" items -- Stage G
closed at v1.34.219, and G2's `WorkloadForecaster` is a real, live
specialist already running in production, so this had a genuine real
consumer to build against rather than fabricated data. G3 (v1.34.219)
already shipped `LearningSpecialist.error_history` but nothing ever
read it back out; `full_diagnostics()['workload_forecaster']` now
exposes `error_history_recent` (bounded, last 40 entries), and a new
dev-console "HCA E5: learning specialist curve" panel
(`renderLearningSpecialistCurve`, `app.js`) renders a live text
sparkline of `candidate_metric` over real recent `learn()` cycles, a
genuine regime-change spike flag (error more than doubling vs. the
prior cycle), and the ten most recent cycles' baseline/candidate/
accepted detail -- same plain-formatted-text presentation discipline
`renderAdaptiveRuntimeStatus` already established, not a canvas chart.

Verified: the new B4 script (16 checks); `verify_b1_global_
workspace.py`/`verify_b2_starvation_gain.py`/`verify_b3_pillar_bus.py`
re-run clean; `verify_ml_g2_workload_forecaster.py` re-run clean
(confirming the diagnostics addition doesn't disturb G2's own real
learn() cycle); `pyflakes` clean on all touched/new Python files (only
the six known pre-existing forward-ref findings in `engine.py`); `node
--check` clean on `app.js`; a full sweep of the rest of `scripts/
verify_*.py` found zero regressions; `scripts/verify_replay_hash.py`
(4000 ticks, seed 777, `--in-process`) -- MATCH, byte-identical;
`scripts/verify_native_soak.py` (3 seeds x 3000 ticks) -- MATCH (both
required this pass since `simulation/engine.py` itself changed, unlike
the last three B1-B3 passes).

## [1.34.225] — HCA Stage B, B3: the real broadcast bus, plus two confirmed-clean porting-backlog audits

Explicit user instruction: "Start B3 and any parallel task of your
choice with most importance." Two independent pieces, one batch.

**B3.** New `hearthmind/cognition/workspace.py`'s `PillarBus`, the
real broadcast bus replacing `SimulationEngine._send_pillar_message`'s
~29 hand-wired sender/receiver arrows (each a fixed Python call naming
one SPECIFIC sender AND one SPECIFIC receiver, e.g. "Nature -> Village"
only). Wraps a `GlobalWorkspace` (B1/B2, untouched) -- any pillar
`subscribe()`s ONCE, GENERICALLY, with one handler that carries no
branch on who sent a bid, and from then on hears every winning bid
this bus arbitrates regardless of sender; `publish_cycle()` is the one
call a caller drives once per real cycle (arbitrate, then broadcast to
every subscriber, including the winner's own submitter, per L3's "every
subscribed subsystem," never "every subsystem except the sender"). The
older point-to-point mechanism (`Pillar.send_message`/`receive_message`,
v1.9.0) is untouched -- migrating the real ~29 arrows onto a real bus
per settlement/domain is separate, larger future work, same "ship the
interface, wire the first real consumer next" discipline as B1's own
~78-site LLM-call-site migration.

New `scripts/verify_b3_pillar_bus.py` (13 checks -- the headline test
straight from the roadmap's own stated B3 test: a real Nature belief,
published through the bus's generic subscription, measurably moves a
downstream Innovation decision (`max(candidates, key=pillar.subject_
confidence)`, the same real pattern this codebase's own Tier 0 sites
already use) with ZERO Nature-specific code anywhere in Innovation's
handler or decision function; the identical unmodified handler then
correctly serves a second, totally different sender (Village) with no
code change; multi-subscriber broadcast delivers the same real winner
to every subscriber; unsubscribe genuinely stops delivery; a genuinely
empty cycle never invokes any subscriber; `PillarBus` composes with a
caller-supplied `GlobalWorkspace` rather than reimplementing
arbitration; re-subscribing the same pillar name replaces, never
stacks) -- all pass, first run, no bug found in the module under test.

**Parallel task, chosen for most importance: confirmed two flagged
C++-porting-backlog audit items still hold clean**, following directly
off last pass's own doc-audit finding -- re-read `economy/farms.py`'s
`apply_nutrient_cycling`/`apply_carcass_decomposition_bonus` and
`settlement/buildings.py`'s ruin-scar/layout-grammar/architecture-
grammar call sites directly against source rather than trusting the
checklist's own unchecked status. Both confirmed still exactly as
documented: the two farms functions are sparse (only ever touch tiles
already present in `soil_fertility`, never a full-grid pass) and
week_end-cadence, no pure-Python hot path reintroduced; `apply_ruin_
scar` fires only inside the native decay path's rare building-removal
branch (once per building's lifetime, not per-tick), and `effective_
layout_style`/`architecture_grammar.building_descriptor` are both
cheap on-demand reads (one build-site-scoring/UI-inspector call site
each), real metadata-only bookkeeping. Checked off with the real
confirmation detail rather than left dangling as "someone should
verify this someday."

Verified: the new script (13 checks); `verify_b1_global_workspace.py`
(17 checks) and `verify_b2_starvation_gain.py` (14 checks) re-run
clean, confirming B3's addition didn't disturb B1/B2's own tie-break/
staleness/broadcast/history behavior; `pyflakes` clean on all touched/
new files; a full sweep of all 60 `scripts/verify_*.py` found zero
regressions. No native module or `simulation/engine.py` code path
touched this pass -- no replay-hash/native-soak re-run needed.

## [1.34.224] — HCA Stage B, B2: unbounded staleness gain, plus a stale-docs fix (G1-G4)

Explicit user instruction: "Start B2 and any parallel task of your
choice with most importance." Two independent pieces, one batch.

**B2.** `GlobalWorkspace.arbitrate()` (`hearthmind/cognition/
workspace.py`) now weights every bid's raw score by a real, deliberately
UNBOUNDED staleness gain before comparing (`STALENESS_GAIN_PER_CYCLE =
0.15`): a `subject` that keeps bidding and losing gets its effective
score multiplied by an ever-growing `(1 + 0.15 * cycles_stale)`, so it
always eventually outscores a merely-higher-raw-score rival, however
large the gap -- "nothing starves on merit," the roadmap's own framing
for B2 ("the *primary* mechanism is competitive... B2.2's bounded-
deferral floor is kept only as a hard backstop beneath it" -- B2.2 here
is the Adaptive Runtime's own already-shipped, untouched priority-class
mechanism, a different system). Staleness resets to 0 the instant its
subject wins; a subject that doesn't bid this cycle is neither
penalized nor rewarded, its clock simply freezes while silent.
`Bid.score` itself is never mutated -- gain is comparison-only. New
`GlobalWorkspace.staleness_for(subject)` accessor.

New `scripts/verify_b2_starvation_gain.py` (14 checks -- the headline
test: a chronically 9x-outscored real subject eventually wins purely
from staleness gain within the constant's own reasoned design horizon;
reset-on-win and resume-from-zero; the gain formula matches hand
computation; a 20x gap is still overcome; the staleness COUNT itself
never caps even after 500 straight losses; a silent subject's clock
freezes rather than ticking; `Bid.score` is never mutated; the
deterministic tie-break still holds with equal staleness on both
sides) -- all pass, first run except two test-design bugs caught and
fixed in the script itself before shipping (an unbroken 200-cycle loop
can't assert staleness is 0 at the end, since the winner keeps
oscillating periodically as staleness rebuilds; a "gained score dwarfs
a million-times-larger rival" assertion was arithmetically wrong for
the linear growth formula at only 500 cycles -- both fixed by asserting
what the module's own linear-growth design actually produces, not a
guessed number), not bugs in the module under test.

**Parallel task, chosen for most importance: a real stale-docs
finding**, caught while re-reading the roadmap's own consolidated Tier
7 checklist (the same list this session's own A1/A2/A3/B1 entries live
in) to scope B2 -- `G1`-`G4` were still shown `[ ]` unchecked, even
though CLAUDE.md has recorded all four as SHIPPED since v1.34.216-.219
(closing HCA Stage G in full), well before B1 (v1.34.223) landed above
them in this exact same list. Re-confirmed each is genuinely shipped by
re-running its own verify script fresh (`verify_ml_specialist.py` 12
checks, `verify_ml_g2_workload_forecaster.py` 23 checks, `verify_ml_
g4_genome_evolution.py` 9 checks, `verify_ml_g3_regime_change.py` 8
checks -- all still pass) before correcting the checkboxes with the
real shipped detail and version numbers, same "verify before trusting
a doc claim" discipline this project's own audits always use.

Verified: the new script (14 checks); `verify_b1_global_workspace.py`
(17 checks) re-run clean, confirming B2's staleness gain didn't disturb
B1's own tie-break/broadcast/history behavior; `pyflakes` clean on both
touched/new files; a full sweep of all 60 `scripts/verify_*.py` (the
two multi-thousand-tick soak scripts aside, which need a longer
timeout than a sweep budget allows but were not required this pass --
neither `simulation/engine.py` nor persisted `World` state nor any
native-function usage was touched) found zero regressions. No native
module or `simulation/engine.py` code path touched this pass -- pure
offline HCA/ML-substrate + docs work, no replay-hash/native-soak
re-run needed.

## [1.34.223] — HCA Stage B, B1: the Global Workspace primitive, plus a real runtime_diagnostics key-mismatch fix

Explicit user instruction: "Start phase 3 B1 and any parallel task of
your choice with most importance." Two independent pieces, one batch.

**B1.** The base coalition-bidding/arbitration engine Stage B's later
refinements (B2-B7) attach to. New `hearthmind/cognition/workspace.py`:
`Bid` (a coalition proposal -- specialist id, subject, score, an
execution-agnostic resolver, a reason) and `GlobalWorkspace`
(`submit()`/`arbitrate()`/`broadcast()`) implementing L3's own per-
cycle mechanism (docs/COGNITIVE-ARCHITECTURE-2026-08-02.md §3) for
steps 1/4/5/6: collect bids, pick one winner (highest score, ties
broken by submission order -- `max()`'s own stability, no RNG anywhere
in the module), broadcast to every subscriber, log the full
competition (winner + every real loser). Step 2 (coalition merge) is a
no-op pass-through until B4; step 3's scoring is the raw bid score
alone until B5's seven-factor formula; step 7 (realised-value credit)
is B7's later addition.

New `scripts/verify_b1_global_workspace.py` (17 checks -- basic
arbitration, the full competition log, a deterministic 20-repeat tie-
break proof, cycle-counter advancement, real subscriber broadcast, a
resolver-never-auto-invoked proof, bounded history, and a real cross-
primitive integration: A1's own `SurpriseSpecialist` feeding real bids
into the workspace, confirming a genuinely novel signal wins
arbitration over three chronically-routine specialists) -- all pass,
first run, no bug found in the module under test.

Deliberately NOT wired into any real production LLM call site this
pass -- B1's own "every LLM call site converted to a bid" is a real,
large, separate migration (~78 sites per A2's own count), same "ship
the interface, wire the first real consumer next" discipline every
prior Stage A/G item has used, not a big-bang rewrite.

**Parallel task, chosen for most importance: a real `runtime_
diagnostics` key-mismatch bug**, found while starting B1 and
re-running the broader verify suite (`scripts/verify_b3_dirty_
events.py`, which failed on unmodified `origin` -- confirmed via `git
stash` in the prior session, flagged then, fixed now).
`full_diagnostics()['runtime_diagnostics']` was keyed by each job's
own Python METHOD name (`_RUNTIME_SCHEDULED_JOB_SCHEDULERS`'s own
keys, e.g. `_update_institution_dormancy`) rather than the real,
friendly `task_id` each dedicated scheduler's one registered `Task`
actually carries (e.g. `institution_dormancy`) -- every real consumer
(the method's own doc comment, the verify script) expected the
latter, so `full_diagnostics()['runtime_diagnostics']
['institution_dormancy']` was silently `None` on every real call since
this dict first shipped (v1.34.214). Fixed by deriving each entry's
real key from its own report's first (only) `tasks` entry -- each
dedicated scheduler holds exactly one task, per B0.3's "one registry
per migrated job" design.

Verified: both new scripts; `verify_b3_dirty_events.py` (16 checks, the
real fix applied) and `verify_runtime_diagnostics.py`/`verify_
scheduler.py`/`verify_task_graph.py`/`verify_dormancy.py`/`verify_b0_
runtime_migrations.py`/`verify_surprise_specialist.py`/`verify_a3_
surprise_overlay.py`/`verify_emergence_surprise_gate.py` re-run clean;
`pyflakes` clean on all touched/new files (only the six known
pre-existing forward-ref findings in `engine.py`); `scripts/verify_
replay_hash.py` (4000 ticks, seed 777, `--in-process`) -- MATCH,
byte-identical; `scripts/verify_native_soak.py` (3 seeds x 3000
ticks) -- MATCH.

## [1.34.222] — HCA Stage A, A3: the surprise map overlay (closes Stage A), plus stale-docs fixes and two A2 regression fixes

Explicit user instruction: "Start A3 and fix stale docs and entries."
Two independent pieces, one batch.

**A3.** The surprise map overlay -- **this closes Tier 7 HCA Stage A in
full** (`A1`->`A2`->`A3`). New `FieldGrid.step_surprise` (`world/
fields.py`, region-aggregated via `_normalize_peak`-then-`diffuse`,
same shape `step_hazard` already established) sourced from a new
`World.settlement_surprise: dict[(x, y), float]` -- keyed by settlement
CENTER position (unlike every sibling scar dict, which is tile-keyed;
resolved once at write time from the settlement NAME `_append_
emergence` already receives), decayed weekly (`terrain_evolution.
decay_settlement_surprise`, `SETTLEMENT_SURPRISE_DECAY_PER_WEEK=0.15`
-- deliberately faster than every sibling scar dict, ~7 weeks vs.
13-20, since a surprise reading should read as "recently," not linger
a season). Written directly by `SimulationEngine._append_emergence`
right after a candidate observation actually clears A1/A2's gate for a
settlement-scoped observation (never on a suppressed one); two
settlements sharing one coarse region take the MAX surprise reading,
not a sum. Persisted (unlike `_emergence_surprise`'s own runtime-only
Welford statistics -- this is a plain derived scalar reading). Reaches
the browser via `set_terrain`'s new `surprise` param (both call sites
updated together); new 19th "fields" overlay mode, own amber-to-gold
color ramp.

New `scripts/verify_a3_surprise_overlay.py` (16 checks) -- all pass,
first run, no bug found in the module under test.

**Two real pre-existing regressions found and fixed in the same pass,
both introduced by A2 (v1.34.221) and only now surfaced** because this
pass was the first to re-run `scripts/verify_b12_emergence_
compression.py`/`scripts/verify_phase0_runtime_hints.py` since A2
shipped -- neither was in that turn's own re-run list, a real gap in
verification coverage, not a defect in A2 itself. Both scripts drove
`_append_emergence` with a STATIC `(subsystem, kind)` key repeated many
times to exercise unrelated mechanisms (B12's compression ladder,
B5.3's cache-scaled emergence cap) -- exactly the "routine, repeated
candidate" shape A2's own gate exists to suppress. Fixed by varying
`subsystem` per call in both scripts so each candidate is a genuinely
distinct surprise-gate key. One further edge case caught in the same
pass: a genuinely first-ever `(subsystem, kind)` key whose own
magnitude is exactly `0.0` scores a real (mathematically correct)
surprise of `0.0` against a fresh key's `0`-prediction/`0`-sigma
baseline -- `verify_b12_emergence_compression.py`'s own magnitude
generator hit this; fixed by shifting its range to never land on
exactly zero, since a genuinely-zero first observation scoring zero
surprise is correct behavior, not a gate bug.

**Stale docs fixed.** `docs/ROADMAP-2026-07-REMAINING.md`'s Tier 7
Stage A checklist (`A1`/`A2`) still read `[ ]` unchecked despite both
shipping in v1.34.220/.221 -- corrected to `[x]` with their real
shipping detail. Its C++ native-porting backlog section (inherited
from an older CLAUDE.md snapshot, "not freshly verified" by its own
admission) claimed `world/weather.py`/`terrain_evolution.py`/
`hydrology.py`/`hydrology_field.py` were largely unported -- a direct
re-read found `climate_drift_batch`/`forest_neighbor_counts`/`maybe_
reclaim_tick`/`hydrology_moisture_tick`/`hydrology_groundwater_tick`
all already shipped and wired since v1.34.218-.220; corrected with
what's actually still open (`tick_erosion`/`tick_wetlands`, both
deliberately deferred as the larger-risk-surface class that mutates
real `Tile`/biome objects) vs. what's genuinely done.

Verified: the new script (16 checks); `verify_b12_emergence_
compression.py` (23 checks, both real fixes applied) and `verify_
phase0_runtime_hints.py` (23 checks, real fix applied) both re-run
clean; `pyflakes` clean on all touched/new files (only the six known
pre-existing forward-ref findings in `engine.py`); `node --check`
clean on `app.js`; `scripts/verify_replay_hash.py` (4000 ticks, seed
777, `--in-process`) -- MATCH, byte-identical; `scripts/verify_
native_soak.py` (3 seeds x 3000 ticks) -- MATCH.

## [1.34.221] — HCA Stage A, A2: gate the emergence log on surprise, plus a C++ backlog wiring fix

Explicit user instruction: "A2 and parallel C++ port." Two independent
pieces, one batch.

**A2.** Gate `world/emergence.py` on surprise, not occurrence.
`SimulationEngine._append_emergence` now scores every candidate
observation through A1's `SurpriseSpecialist` (`self._emergence_
surprise`, keyed by `f"{subsystem}:{kind}"`) BEFORE deciding whether it
reaches `World.emergence_log` at all. The specialist's running model
updates for every candidate regardless of outcome (`SurpriseSpecialist.
score()` always calls `observe()`), so a routine candidate's own
surprise genuinely falls the more it repeats, while a candidate lacking
a natural `magnitude` scale is scored against a fixed neutral proxy
(`EMERGENCE_SURPRISE_NEUTRAL_MAGNITUDE=0.4`) rather than a fabricated
per-call number. New `EMERGENCE_SURPRISE_THRESHOLD=0.3` -- a candidate
whose surprise doesn't clear it is silently suppressed, never appended
(no id consumed, no eviction/compression triggered). New
`SimulationEngine._emergence_surprise_attempted_total`/`_emergence_
surprise_suppressed_total` (runtime-only counters) surfaced via
`full_diagnostics()['emergence_surprise']`.

New `scripts/verify_emergence_surprise_gate.py` (11 checks -- A2's own
stated test, reproduced against a real `SimulationEngine`/`_append_
emergence` with a synthetic candidate stream shaped like the doc's own
reported soak numbers: 466 of 500 candidates are near-identical
"content agent decided to socialize"-style `unexplained_shift` entries
with no set magnitude -- the real production shape -- and 34 are
genuinely distinct rare `opportunity`/`bottleneck`/`anomaly`/
`novel_combination` entries; confirmed the LOGGED `unexplained_shift`
share drops from the doc's reported 93.2% to 2.9% of 35 total logged
entries, well under the stated < 40% bound, while every genuinely
rare/distinct candidate still logs) -- all pass. One real test-fixture
correction made before shipping (not a bug in the module under test):
the first aggregate-share draft fed the routine candidates a small
cycling magnitude sequence rather than the real production shape (no
magnitude at all), which kept re-triggering marginal surprise near the
threshold and produced a 77.5% logged share instead of the intended
sub-40% -- fixed by matching the actual call site's real behavior.

**C++ porting backlog, parallel track -- a wiring gap, not a new
module.** Module 12's already-shipped shared primitive
(`bounded_random_walk_step`, `cpp/src/bounded_random_walk.cpp`, backing
`Settlement.tick_temperament`/`tick_player_standing`/`tick_relation`
and `world/hydrology.py`'s lake-level nudge) was never actually
consumed by `Population._tick_traits` (H6's monthly per-agent trait
mean-reversion), even though that method's own formula is the EXACT
same computation every sibling call site already delegates to this
function. Wired directly -- no rebuild needed. Verified via a direct
5000-trial randomized equivalence check against the pure-Python
fallback (0 mismatches).

Verified: both new/updated checks; `pyflakes` clean on all touched
files (only the six known pre-existing forward-ref findings in
`engine.py`); `scripts/verify_ml_evolution.py`/`verify_ml_
specialist.py`/`verify_ml_substrate.py`/`verify_ml_g2_workload_
forecaster.py`/`verify_ml_g4_genome_evolution.py`/`verify_ml_g3_
regime_change.py`/`verify_surprise_specialist.py`/`verify_ca_
operators_native.py`/`verify_terrain_neighbor_count_native.py` re-run
clean; `scripts/verify_replay_hash.py` (4000 ticks, seed 777,
`--in-process`) -- MATCH, byte-identical (load-bearing -- this pass
changes what reaches persisted `World.emergence_log` state and
re-wires a persisted-per-agent-trait scalar step); `scripts/verify_
native_soak.py` (3 seeds x 3000 ticks) -- MATCH.

## [1.34.220] — HCA Stage A, A1: precision-weighted surprise scoring, plus a third C++ porting backlog pickup

Explicit user instruction: "Phase 2 A1 and parallel c++ porting." Two
independent pieces, one batch.

**A1.** `predict()`/`error()` on specialists; precision-weighted
surprise scoring -- the first item of Tier 7 HCA Stage A. New
`hearthmind/cognition/surprise.py`'s `SurpriseSpecialist`: one running
forward model per string key (Welford's online algorithm -- O(1) per
observation, no stored history), implementing L1's `predict()`/
`observe()`/`error()` trio per the HCA doc's own formula, `surprise =
|actual - predicted| / (sigma + eps)`. Precision-weighting via the
running standard deviation is what lets a chronically noisy channel's
typical deviation score LOWER than the same raw gap on a tightly-
clustered signal, and what lets a recurring severe signal's own
surprise genuinely fall once it stops being novel. `bid()`/`learn()`
deliberately out of scope -- `bid()` needs Stage B's real workspace
(unbuilt), and a trained `learn()` forward model is G1/G2's already-
shipped `LearningSpecialist` machinery applied to a new specialist
family, not reinvented here.

New `scripts/verify_surprise_specialist.py` (14 checks -- A1's own
stated test, reproduced synthetically since no live archive exists in
this offline environment: a routine, near-identical repeated signal
["content agent socialises"] scores < 0.1; a rare, severe, first-
occurrence signal ["family extinction during prosperity"] scores >
2.0; the formula matches the doc's own math by hand; precision-
weighting genuinely discounts a chronically noisy channel; a recurring
severe signal's own surprise falls once learned; `score()` is
atomically equivalent to `error()`-then-`observe()`; the wrong method
ordering silently understates surprise) -- all pass, first run, no bug
found. Deliberately NOT wired into any real production job this pass
-- `world/emergence.py`'s own consumer (gating the emergence log on
surprise instead of occurrence) is `A2`, a distinct, larger item
depending on this primitive existing first.

**C++ porting backlog, parallel track.** New `cpp/src/terrain_
neighbor_count.cpp`: `world/terrain_evolution.py`'s `_tick_fallow`, the
weekly full-grid pass gating reforest eligibility -- for every
GRASSLAND tile, counts how many of its 4 orthogonal neighbors are
FOREST, same 4-neighbor bounds-checked shape `ca_operators.cpp`'s
`ca_diffuse` already established, just counting booleans instead of
averaging floats. Distinct from the pre-existing `_native_maybe_
reclaim_tick` (its own, separate, later-pass neighbor recount for the
actual reclaim roll's real intra-pass dependency) -- `_tick_fallow`
runs first, purely to determine which tiles are even eligible this
week. `_is_developed`'s settlement/farm-position lookups stay in
Python (position-indexed, not a hot scan); only the pure 4-neighbor
boolean count crosses the boundary, via a plain forest/not-forest grid
precomputed once in Python.

New `scripts/verify_terrain_neighbor_count_native.py` (8 checks -- 2000
randomized trials against the pure-Python reference, 0 mismatches;
edge cases for an empty grid, a single forested/non-forested tile, an
all-forest 5x5 grid, an all-non-forest grid, and two non-square grids)
-- all pass, first run, no bug found. New toggle entry in `scripts/
verify_native_soak.py`.

Verified: all four new scripts; `pyflakes` clean on all touched/new
files; `scripts/verify_replay_hash.py` (4000 ticks, seed 777,
`--in-process`) -- MATCH, byte-identical (load-bearing this time --
this pass touches `world/terrain_evolution.py`'s real production tick
path); `scripts/verify_native_soak.py` (3 seeds x 3000 ticks) -- MATCH.
A1 touched no native module or `simulation/engine.py` code path (pure
offline substrate); the `terrain_neighbor_count` port is the only
native-module change this pass.

## [1.34.219] — HCA Stage G, G3: regime-change re-adaptation made testable (closing Stage G), plus a second C++ porting backlog pickup

Explicit user instruction: "Continue G3 and c++ backlog." Two
independent pieces, one batch. **This closes Tier 7 HCA Stage G in
full** (G1 v1.34.216, G2 v1.34.217, G4 v1.34.218, G3 here).

**G3.** "Forget obsolete assumptions," made testable. Investigated
before writing any new mechanism: does the already-shipped `G1`
`learn()` loop (`continual_train_mlp` + `ReplayBuffer` + the shadow
gate) already re-adapt when a pattern genuinely stops holding, or does
replay rehearsal of stale examples actively resist adaptation? A
direct synthetic test (two distinct linear regimes with opposite-
signed coefficients, sharing one input range) confirmed it already
does -- the shadow gate always compares a candidate against a holdout
drawn from the world AS IT IS NOW, never the stale regime, so a
candidate genuinely closer to the new pattern keeps winning gate
comparisons regardless of what's mixed into replay. No new forgetting
mechanism was invented for a problem that doesn't reproduce.

The one real gap the investigation found: no specialist exposed its
own prediction-error trace over time -- HCA's own `E5` item (a future
per-specialist learning-curve Observatory panel, explicitly gated on
`G3`) needs exactly that series to plot a regime-change spike-then-
recovery. New `LearningSpecialist.error_history` (`hearthmind/ml/
specialist.py`, a bounded `deque`, `ERROR_HISTORY_MAX=200`): one entry
per real `learn()` call (never a skipped/synthetic one) -- `{tick,
baseline_metric, candidate_metric, accepted}`.

New `scripts/verify_ml_g3_regime_change.py` (8 checks -- G3's own
stated test: a real specialist reaches a genuine low steady-state on
regime A over 6 real `learn()` cycles; the very first post-shift cycle
on regime B genuinely spikes error past 3x the pre-shift floor; it
falls back within the stated-in-advance bound of 15 cycles -- recovered
at real cycle 14 of 15 on the actual run; `error_history`'s own
recorded values reproduce the real spike at the shift boundary, every
entry carries the real expected fields, and the history stays
genuinely bounded over 250 real cycles) -- all pass, first run, no bug
found in the module under test.

**C++ porting backlog, parallel track.** New `cpp/src/ca_operators.
cpp`: `world/ca_operators.py`'s `diffuse`/`reaction_diffuse` -- the
exact follow-up `hydrology_tick.cpp`'s own docstring flagged. Neither
function crosses a domain object at all (a plain grid of doubles in, a
plain grid of doubles out, the simplest port shape in this codebase);
`diffuse` alone is called roughly a dozen times every real tick (once
per `FieldGrid` field). Porting `reaction_diffuse` also transparently
unblocks `hydrology_field.py`'s `tick_snowpack`, which calls it
directly -- `tick_snowpack` needed no changes to pick up the native
path. `cellular_step` (this module's third operator) deliberately NOT
ported -- its `rule` parameter is a Python callable that can't cross
the pybind11 boundary without specializing per consumer, same "resolve
callables/objects in Python" discipline every prior module in this
queue already follows. New `scripts/verify_ca_operators_native.py` (9
checks -- 2000 randomized trials each for `ca_diffuse`/`ca_reaction_
diffuse` against the pure-Python reference, 0 mismatches; edge cases
for an empty grid, a zero/negative rate, a single tile, a non-square
grid, and mass-conserving reaction transfer floored at 0.0 on both
sides) -- all pass, first run, no bug found. New toggle entries in
`scripts/verify_native_soak.py`.

Verified: both new scripts; `pyflakes` clean on all touched/new files;
`verify_ml_evolution.py`/`verify_ml_specialist.py`/`verify_ml_
substrate.py`/`verify_ml_g2_workload_forecaster.py`/`verify_ml_g4_
genome_evolution.py` re-run clean (confirming `error_history` doesn't
disturb any existing `learn()` behavior); `scripts/verify_replay_
hash.py` (4000 ticks, seed 777, `--in-process`) -- MATCH, byte-
identical; `scripts/verify_native_soak.py` (3 seeds x 3000 ticks) --
MATCH. G3 touched no native module or `simulation/engine.py` code path
(pure offline ML substrate); the `ca_operators` port is the only
native-module change this pass.

## [1.34.218] — HCA Stage G, G4: genome evolution wired to a real L1 consumer, plus a C++ porting backlog pickup

Explicit user instruction: "Start G4 and parallels c++ backlog." Two
independent pieces, one batch.

**G4.** L6's `GenomePopulation`/`ModelGenome` (`hearthmind/ml/
evolution.py`) previously scored every genome through `train_and_
score_genome`, a bare `train_mlp_sgd` call -- a parallel evaluation
path that never touched G1's shipped `learn()` interface. New `train_
and_score_genome_via_specialist`: builds a genome-shaped model, wraps
it in a real `LearningSpecialist`, and scores the genome through the
exact same `learn()` -> shadow-gate cycle a live specialist would use
-- `replay_fraction`/`epochs`/`learning_rate` genes map directly onto
`learn()`'s own keyword arguments. Fitness is read from the real
`candidate_metric` regardless of accept/reject (a genome is scored on
how well its hyperparameters actually trained, not on whether that
training survived gating this once), with the same NaN-guard
discipline the pre-existing scorer already used.

New `scripts/verify_ml_g4_genome_evolution.py` (9 checks -- a real
`GenomePopulation`'s mean fitness climbs monotonically across 8 real
generations against the new L1 consumer; the genome-scoring path
reproduces an identical hand-driven `LearningSpecialist.learn`
outcome; a sabotaged retrain is genuinely rejected by the real shadow
gate with the live model byte-identical before/after; a genuinely
NaN-diverged genome degrades to fitness 0.0 rather than crashing; every
bred genome's genes stay in bounds; the pre-existing scorer is
unaffected) -- all pass, one real test-calibration fix made before
shipping: the first sabotage scenario NaN-diverged the candidate's
loss outright, making `candidate_metric > 0.0` unreliable (`nan > 0.0`
is `False`); split into a real shadow-gate-rejection proof (moderate
wrong target) and a real NaN-guard proof (an intentionally-diverging
target), not a bug in the module under test.

**C++ porting backlog, parallel track.** New `cpp/src/hydrology_
tick.cpp`: the full-grid scalar passes behind `world/hydrology_
field.py`'s `tick_hydrology`/`tick_groundwater` (A11, live since
v1.13.0), ported per that module's own docstring explicitly inviting
this once the shape proved itself live, following `soil_fertility.
cpp`'s precedent. Enum/object resolution stays in Python (the caller
precomputes a water-biome boolean grid and elevation grid before
calling in); `tick_snowpack` (depends on the still-unported `ca_
operators.reaction_diffuse`) and `tick_erosion` (writes real `Tile`
objects with biome reclassification) stay pure Python, a materially
larger risk surface flagged for separate future work. New `scripts/
verify_hydrology_tick_native.py` (5 checks -- 2000-trial randomized
equivalence for each ported function against a plain-Python reference
plus edge cases) -- all pass, first run, no bug found. New toggle
entries in `scripts/verify_native_soak.py`.

Verified: both new scripts; `pyflakes` clean on all touched/new files
(only the six known pre-existing forward-ref findings in `engine.py`);
`verify_ml_evolution.py`/`verify_ml_specialist.py`/`verify_ml_
substrate.py`/`verify_ml_g2_workload_forecaster.py` re-run clean;
`scripts/verify_replay_hash.py` (4000 ticks, seed 777, `--in-process`)
-- MATCH, byte-identical; `scripts/verify_native_soak.py` (3 seeds x
3000 ticks) -- MATCH. G4 touched no native module or `simulation/
engine.py` code path (pure offline ML substrate); the hydrology port
is the only native-module change this pass.

## [1.34.217] — HCA Stage G, G2: WorkloadForecaster gets a real continual-retrain cadence

Explicit user instruction: "Build G2." Wires B8.1/L3.2's `WorkloadForecaster`
-- a real, trained MLP with no retrain loop attached, per its own long-
standing "not wired into any real cadence" note -- to G1's `Learning
Specialist`, closing three previously-separate flagged gaps at once
(Part B's B8.1-B8.3, Tier 6's L3.2, HCA's own G2 test case all name the
identical unwired model).

New `SimulationEngine._maybe_tick_workload_forecaster` (daily, a real
`_TICK_JOBS` entry): samples the forecaster's own real feature vector
every day -- current backlog (`_effective_backlog()`), real per-day
dialogue/cognition call counts (two new lightweight counters,
`_dialogue_calls_today`/`_cognition_calls_today`, incremented at the
three genuine LLM dispatch points: `_run_cognition`/`_run_dialogue`/
`_run_voice_dialogue`), a real disaster-pressure flag (reusing
`FLOOD_PRESSURE_THRESHOLD`/`HEATWAVE_PRESSURE_THRESHOLD`), a real
recent-festival flag (`last_life_events`), and real season -- alongside
a snapshot of the real cumulative `CognitionRunner.calls_attempted`
counter. `WORKLOAD_SAMPLE_HORIZON_DAYS` later, each sample resolves
into a real `(features, observed_call_volume)` training example: the
observed value is the REAL delta in `calls_attempted` over that exact
window, never a guess, scored against the real `ForecastAccuracy
Tracker`. Monthly, once `WORKLOAD_MIN_EXAMPLES_TO_RETRAIN` real
examples have banked, retraining goes entirely through `Learning
Specialist.learn` -- G1's real shadow-gated loop, not a second training
path. `_workload_forecaster.model` is explicitly kept in sync with
`_workload_specialist.model` after every attempt, since `learn()` may
swap in a whole new `MLP` object on acceptance rather than mutating the
old one in place. Every attempt (accepted or rejected, never a silent
no-op) logs to a new bounded `_workload_learn_log`, surfaced via
`full_diagnostics()['workload_forecaster']` alongside the live
reliability weight and pending/banked example counts.

New `scripts/verify_ml_g2_workload_forecaster.py` (23 checks -- G2's
own stated test: a real training example's target matches the real
observed `calls_attempted` delta exactly; no retrain fires before a
real month_end or with too few banked examples; a real month_end WITH
enough examples fires a real `learn()` cycle through `Learning
Specialist` with the forecaster's model kept in sync afterward; the
real shadow gate provably REJECTS a deliberately-sabotaged retrain --
confirmed the live model's weights are byte-identical before/after the
rejection; `full_diagnostics()` surfaces real, not placeholder, state;
a real 3000-tick production run through `_tick_once` with the new job
live in `_TICK_JOBS` never crashes and genuinely accumulates real
samples/examples) -- all pass. Two real test-fixture bugs caught and
fixed in the script itself before shipping, not bugs in the module
under test: the observed-delta check initially applied the call-volume
bump BEFORE sampling instead of during the horizon window (the real
feature-then-resolve semantics measure volume AFTER the sample, not
before it); the soak check initially called `asyncio.run(eng.
_tick_once())` once per tick, discarding the event loop each time and
crashing `_schedule_llm_job`'s `asyncio.create_task` on the very first
real LLM-scheduled job -- fixed by driving the whole soak inside one
`asyncio.run(...)` call, matching every sibling multi-tick soak
script's existing pattern.

Verified: the new script (23 checks); `pyflakes` clean on `simulation/
engine.py` (only the six known pre-existing forward-ref findings) and
the new script; `verify_ml_specialist.py`/`verify_ml_substrate.py`/
`verify_ml_evolution.py`/`verify_scheduler.py`/`verify_task_graph.py`/
`verify_runtime_invariant.py`/`verify_dormancy.py`/`verify_tuning.py`/
`verify_b6_adaptive_concurrency.py`/`verify_b7_hardware_citizenship.py`/
`verify_b8_predictive_scheduling.py`/`verify_hardware_profile.py`/
`verify_runtime_diagnostics.py`/`verify_phase0_runtime_hints.py`
re-run clean; `scripts/verify_replay_hash.py` (4000 ticks, seed 777,
`--in-process`) -- MATCH, byte-identical (load-bearing this time,
unlike G1 -- this pass touches `simulation/engine.py`'s own `__init__`
and tick-dispatch state); `scripts/verify_native_soak.py` -- MATCH.

## [1.34.216] — HCA Stage G, G1: the learn() interface, wired to Tier 6's L5 substrate

Explicit user instruction: "Start phase 1 G1." Tier 7 HCA's first line
of real code (everything prior was docs-only).

New `hearthmind/ml/specialist.py`'s `LearningSpecialist`/`LearnResult`:
`predict()` (delegates to the wrapped `MLP.forward`) plus a real
`learn()` orchestrating Tier 6 L5's already-shipped `ReplayBuffer`/
`continual_train_mlp`/`passes_shadow_gate` -- no new learning
mechanism invented. `learn()` never trains the live model in place
(`continual_train_mlp` mutates its argument directly, which would make
a shadow-gate check meaningless): it clones the live model, trains the
clone, evaluates it against caller-supplied held-out examples, and
only swaps it in if the real shadow gate agrees it didn't regress. A
rejected candidate's new examples still enter the replay buffer
regardless -- lived history, not learned success.
`observe()`/`error()`/`bid()` are explicitly out of scope (Stage A/B's
own unbuilt items) -- this ships the smallest real thing that makes
`learn()` meaningful on its own.

New `scripts/verify_ml_specialist.py` (12 checks, all pass, first run,
no bug found) -- G1's own stated test: prediction error on a fixed
held-out set trends down across real `learn()` cycles on a stationary
synthetic signal; a real shadow-gate rejection proven via a
deliberately-sabotaged retrain (the live model's weights and held-out
performance confirmed byte-identical before/after); the no-new-
examples and no-holdout degrade-gracefully cases. Verified: `pyflakes`
clean; `verify_ml_substrate.py`/`verify_ml_evolution.py` re-run clean.
No native module, persisted `World` state, or `simulation/engine.py`
code path touched -- pure offline ML substrate, no replay-hash/
native-soak re-run needed.

## [1.34.215] — Phase 0 shipped, HearthBench added to the build sequence, roadmap decluttered

Explicit user instruction: "Yes full picture in one place and cleanup
the roadmap as it looks very cluttered and long. Also ship phase 0."
Three independent pieces, one batch.

**Phase 0 shipped.** Three of the four originally-scoped cheap Part B
gaps wired for real; the fourth investigated and honestly reclassified
rather than forced. `select_strategy`'s `dormancy_aggressiveness` hint
now scales `SimulationEngine._dormancy_idle_threshold`, applied at all
four real B4.2 dormancy candidates' idle-checks thresholds
(institutions/ideas/traditions/settlements). `cache_size_hint` now
scales `SimulationEngine._effective_emergence_log_cap`, applied at
`World.emergence_log`'s own eviction cap. `worker_count_hint` was
investigated and confirmed to have no real consumer possible in this
codebase today (B0's prime invariant bans real thread/process pools in
gameplay code, and the one real async concurrency knob is `llm_max_
concurrent_hint`'s own territory) — documented directly on `Strategy`'s
docstring rather than silently left to look unwired. `TunableRegistry`'s
three pacing constants (`llm_pressure_slowdown_start_ratio`/`speedup_
start_ratio`/`min_speedup_multiplier`) are now genuinely live via a new
`SimulationEngine._pacing_tunable` helper, closing B6.3's own "metadata
only" gap. `full_diagnostics()['runtime_diagnostics']` now reports
every real B0.3-migrated scheduler (~56 entries), not just `institution_
dormancy`. `B14.3`'s `batch_size_for_storage` was investigated and found
to need a real batched-write mechanism first (the snapshot writer is
still one `INSERT` per row) — honestly moved to the roadmap's
"remaining independent Part B cleanup" list rather than wired to a fake
consumer.

New `scripts/verify_phase0_runtime_hints.py` (23 checks, all pass,
production-path). Verified: `pyflakes` clean; the full existing
`verify_*.py` regression sweep re-run clean; `scripts/verify_replay_
hash.py` (4000 ticks, seed 777, `--in-process`) MATCH; `scripts/verify_
native_soak.py` MATCH. No native module touched.

**HearthBench added to the "full picture."** The dependency-ordered
build sequence filed in v1.34.214 covered Part B (Adaptive Runtime) and
Tier 7 (HCA) but omitted HearthBench (Tier 5 Part A) entirely — a real
gap, since `B15.5` above depends on a HearthBench runner existing. New
parallel-track section in `docs/ROADMAP-2026-07-REMAINING.md`: only
`A0`/`A1.1`/`A1.2` shipped; the remaining 11 steps (`A2` model adapter
through `A13` CI regression guard) ordered internally, `A4`'s scoring
decision named as the real fork point everything downstream waits on.

**Roadmap decluttered.** Explicit user complaint ("looks very
cluttered and long"), previously flagged unresolved at v1.34.212.
`docs/ROADMAP-2026-07-REMAINING.md`'s own "Priority ordering" section
carried a ~1,800-line verbatim duplicate of Tier 0/Tier 0.5's full
turn-by-turn slice history — already fully covered, in better-
consolidated form, by CLAUDE.md's own "Current state" log, and Tier 0
itself has been closed/reclassified to ongoing opportunistic
maintenance since v1.34.148 (no longer blocks anything, so a full
slice-by-slice history no longer earns its place in a section whose
own stated purpose is ranking, not detail). Collapsed to two short
paragraphs pointing at CLAUDE.md. File size: 6,031 -> 4,265 lines
before this pass's HearthBench/Phase-0 additions (~29% smaller); every
other section (the A1-A25/B1-B9/C1-C5 per-item technical detail, the
C++ porting backlog, the standing-discipline/scope-trim notes) was
checked and left intact — that content is substantive design reference,
not duplicate history, and cutting it would lose real information.

## [1.34.214] — Docs: dependency-ordered Adaptive Runtime + HCA build sequence

Explicit user request: "push this to roadmap, proper sequence of
building components so nothing is blocked by anything else and each
step ships a complete usable code... reordering of the previous one."
Docs-only, no code changed. New `docs/ROADMAP-2026-07-REMAINING.md`
section, "Adaptive Runtime & HCA — dependency-ordered build sequence,"
inserted right after the existing Tier 5/6/7 checklists (which remain
the categorical reference — this section only fixes build order).
Reorders every currently-open Part B (Adaptive Runtime) item, every
Tier 6 item HCA's Stage G/H depend on, and all of Tier 7's HCA stages
into 8 numbered phases (Phase 0 closes four already-flagged Part B
gaps with zero new design; Phase 1 = Stage G; Phase 2 = Stage A; Phase
3 = Stage B; Phase 4 = Stage H, the literal "Runtime becomes a mind"
milestone; Phase 5 = Stage C; Phase 6 = Stage D; Phase 7 = Stage E,
shipped incrementally per-phase rather than batched) plus two
parallel/optional tracks (semantic embedding → `F1`; remaining
independent Part B cleanup) and a third fully-independent Tier 6 list
(`L2.1`/`L2.2`/`L4.1`). Honors all four dependencies the HCA doc states
explicitly (`H1` needs Stage B+G, `B7` needs Stage G, `E5` needs Stage
G, `E6` needs Stage H, `F1` needs `L1.1`) plus one necessary dependency
the doc implies but doesn't state (`B5`'s surprise-scoring factor needs
`A1` to exist first, so Stage B's `B5` step specifically follows Stage
A even though Stage B doesn't wait on it as a whole). Notably, Phase
1's `G2` (wiring `B8.1`/`L3.2`'s already-trained `WorkloadForecaster`
to a real retrain cadence) closes three previously-separate flagged
gaps in one item — Part B's B8.1-B8.3, Tier 6's L3.2, and HCA's own G2
test case all point at the identical unwired model.

## [1.34.213] — Adaptive Runtime: automatic hypothesis cadence + a real dev-console panel

Explicit user instruction: "Do both and keep building adaptive runtime
to what I originally wanted" (a rendered dev-console panel instead of
raw JSON, and an automatic cadence for the manual-only B13 hypothesis
loop).

**Automatic cadence for `llm_max_concurrent`'s `HypothesisLoop`.** New
`SimulationEngine._maybe_auto_llm_concurrency_hypothesis` (monthly),
strictly gated so it can never fight B6's live daily `BangBangController`
over the same tunable: it only fires once the reactive controller has
made no real change (per `self._adaptive_tuning_log`'s own `tick`
field) for `LLM_CONCURRENCY_AUTO_HYPOTHESIS_QUIET_DAYS` (14) real
days, and the proposed value is always `select_strategy`'s own
hardware-derived `llm_max_concurrent_hint` — closing the loop that
hint's own docstring named as still open (previously only a downward-
only cap, now periodically tested as a real candidate value). The
manual dev-console/API trigger is unchanged; both paths share one new
spawn helper (`_spawn_llm_concurrency_hypothesis`) and results are
tagged `source: "auto"`/`"manual"`.

**Real dev-console panel.** New "Adaptive runtime" panel
(`renderAdaptiveRuntimeStatus` in `app.js`) renders `host_probe`/
`machine_profile`/`adaptive_tuning_log_recent` as readable text
instead of raw JSON — cores/RAM/swap/load/thermal state, the
persisted machine profile's measured throughput/storage speed, the
current hardware-derived hint, and every real automatic concurrency
change. Pure presentation over already-existing `full_diagnostics()`
data. The B13 hypothesis-result line now also shows `[auto]`/
`[manual]`.

New `scripts/verify_auto_llm_concurrency_hypothesis.py` (12 checks) —
all pass; one real off-by-one caught and fixed in the verify script
itself (a fresh engine starts at tick 0, so representing a genuinely
"old" reactive-log entry needs the clock advanced first), not a bug
in the module under test.

Verified: the new script; `node --check` clean; a live Playwright
pass confirming the new panel renders real formatted text after
clicking "Full diagnostic report"; full existing verify-script suite
re-run clean; `pyflakes` clean; `scripts/verify_replay_hash.py` (4000
ticks, seed 777) — MATCH; `scripts/verify_native_soak.py` (3 seeds x
3000 ticks) — MATCH.

## [1.34.212] — Tier 6 L1.2's real gameplay consumer + diagnostics; roadmap markdown fix

Explicit user instruction: "Continue that wire everything and expose in
diagnostics so that I can check it on my own live machine. Ship a
complete version now. Also fix roadmap remaining rendering issues."

**L1.2's real first gameplay consumer.** New `SimulationEngine._detect_
social_bridge` mirrors the already-real `_detect_social_hub`/
`Settlement.social_hub_agent_id` pattern (season cadence, zero LLM
cost, edge-triggered emergence entry) for `compute_social_features`'s
`bridge_score` instead of centrality. New `Settlement.social_bridge_
agent_id` (persisted, legacy-backfilled to `None`) names the living
agent who genuinely connects otherwise-separate parts of a
settlement's social graph — `None` while no member has a real
positive bridge score. New "Social bridge" main-UI stat tile next to
the existing "Social hub" tile.

**Diagnostics.** `full_diagnostics()['social_features']` now surfaces
both the persisted per-settlement `social_hub_agent_id`/`social_
bridge_agent_id` verdicts and a live, on-demand `compute_social_
features()` sample (`agents_measured`, `top_bridge`, `top_centrality`)
over the current population — reachable on `/diagnostics` on a live
deployment without reproducing a run, and confirmed genuinely
JSON-serializable.

**Roadmap markdown fix.** Found and fixed a real GitHub-rendering
break in `docs/ROADMAP-2026-07-REMAINING.md`: a `+` sign joining two
identifiers ("`Settlement.layout_style` + `layout_grammar.drift_
layout_style`") had word-wrapped so the bare `+` landed at the start
of a line — GFM interprets a line-leading `+` as a bullet-list marker,
which CAN interrupt a paragraph, so it rendered as an unwanted
one-item list breaking the paragraph in two. Reworded to "plus"
instead. Verified via a systematic automated scan of the whole 5745-
line document (code-span/paragraph crossings, setext-heading
collisions, raw HTML-like tags, mixed bullet markers, ordered-list
paragraph interruption) — no other break found. The doc's length
(5745 lines) is a separate, known, unresolved concern — already
flagged in the doc's own "Open-task checklist" section (v1.34.64); a
full restructuring pass is out of scope for this batch and not
attempted.

New `scripts/verify_social_bridge_wiring.py` (14 checks) — all pass,
first run, no bug found.

Verified: the new script; `scripts/verify_social_features.py` (19
checks)/`scripts/verify_b12_emergence_compression.py` (23 checks)
re-run clean; full existing verify-script suite re-run clean;
`pyflakes` clean; `node --check` clean; `scripts/verify_replay_
hash.py` (4000 ticks, seed 777) — MATCH; `scripts/verify_native_
soak.py` (3 seeds x 3000 ticks) — MATCH.

## [1.34.211] — Part B: B12's real first wiring; Tier 6 L1.2 social structure features

Explicit user instruction: "Continue part B and parallely tier 6." Two
independent pieces, one batch, same pattern as v1.34.207-.210.

**Part B: B12's real first wiring.** `World.emergence_log`'s own
eviction (`SimulationEngine._append_emergence`, capped at `EMERGENCE_
LOG_MAX_STORED`) previously discarded overflow entries via plain list
truncation — the exact gap B12's own doc text named ("the DB is
already ~60 MB... a flat row-count cap but no reconstructable archived
detail"). New `SimulationEngine._emergence_compression`, a real
`CompressionLadder` instance (already-shipped B12.1-B12.3 machinery,
v1.34.179) — deliberately runtime-only, never persisted in `World.
to_dict()`/`from_dict()`, same discipline every `DormancyManager`
instance in this codebase already uses. An evicted batch is now
`ingest()`-ed into the RAW stage and `maybe_compress` condenses it via
a new real `condense_fn`, `_condense_emergence_entries` (tick range,
per-kind tally, the single highest-magnitude entry's own summary as a
representative sample) — `prune_to_capacity(EMERGENCE_COMPRESSION_
ARCHIVE_MAX)` enforces B12.2's real hard ceiling. Surfaced via `full_
diagnostics()['emergence_compression']`. Scoped to one stage
transition (RAW → archived digest), not the full five-stage cascade —
wiring the remaining stages onto a real chronicle/documentary/
culture-digest producer chain per stage stays open. New `scripts/
verify_b12_emergence_compression.py` (23 checks) — all pass; one real
off-by-one caught and fixed in the verify script itself (reaching
`EMERGENCE_LOG_MAX_STORED` exactly still evicts nothing — `>` is a
strict inequality), not a bug in the module under test.

**Tier 6, L1.2 — social structure features.** New `hearthmind/ml/
social_features.py`'s `compute_social_features(agents)`: reuses
`world/graph_algorithms.py`'s already-real `build_relationship_graph`/
`degree_centrality` directly (each called once, shared across every
per-agent feature) rather than a parallel graph representation, per
the architecture doc's own "downgraded from a full GNN" scoping.
`community_id` (a real connected-component BFS over the same
positive-weight graph — deliberately graph-only, not an `Institution`/
FACTION lookup, per this project's own "substrate reused upward, never
the reverse" dependency discipline) and `bridge_score` (a Burt's-
constraint-style structural-holes proxy: the fraction of an agent's
own neighbor pairs NOT themselves directly connected) are the two
named features with no prior implementation; `neighborhood_sentiment`
(mean edge weight) rounds out the four. New `scripts/verify_social_
features.py` (19 checks) — all pass, first run, no bug found. Not
wired into any real consumer this pass — L2.1/L2.2 remain the doc's
own named future consumers.

Verified: both new scripts (42 checks total); `verify_task_graph.py`/
`verify_scheduler.py`/`verify_dormancy.py`/`verify_runtime_
invariant.py`/`verify_ml_substrate.py`/`verify_value_model.py`/
`verify_belief_calibration.py`/`verify_b4_settlement_dormancy.py`/
`verify_b4_tradition_dormancy.py`/`verify_b4_idea_dormancy.py`/
`verify_b0_runtime_migrations.py`/`verify_b14_snapshot_diff.py`/
`verify_b14_persistence_scheduling.py` re-run clean; `pyflakes` clean
(only the six known pre-existing forward-ref findings in `engine.py`);
`scripts/verify_replay_hash.py` (4000 ticks, seed 777, `--in-process`)
— MATCH; `scripts/verify_native_soak.py` (3 seeds x 3000 ticks) —
MATCH.

## [1.34.210] — Part B: B4.2's fourth dormancy candidate; Tier 6 L4.1 belief calibration

Explicit user instruction: "Continue Big Bang B and parallel other
tier." Two independent pieces.

**Part B: "inactive settlements" (B4.2's fourth of five named
candidates).** Reframed from the harder Body-deterministic-ticking
shape earlier entries flagged this candidate as needing: gates the
already-real `_job_target()` month-indexed round-robin (WHICH named
settlement gets this month's town_brain/beliefs/chronicle/... LLM
narration) rather than skipping `Population.tick()`/`WildlifeGrid.
tick()` — the identical Mind-layer-attention-only shape institutions/
ideas/traditions already proved safe. New `SimulationEngine._update_
settlement_dormancy` (monthly): a named settlement's coarse
fingerprint (population, era, building count, tech level — not
materials/currency, which drift every tick) unchanged across 3
consecutive monthly checks sleeps it via `DormancyManager`, any real
change wakes it immediately. `_job_target` excludes sleeping
settlements, falling back to the full list when everything's asleep
(a real no-op for the common single-settlement case). New `scripts/
verify_b4_settlement_dormancy.py` (19 checks) — all pass, first run,
no bug found in the module under test. **Closes four of B4.2's five
named candidates** — only "distant wildlife" remains open.

**Tier 6, L4.1 — belief confidence calibration.** New `hearthmind/ml/
belief_calibration.py`: `BeliefConfidenceCalibrator` (a thin domain
wrapper over L0's already-shipped `PlattCalibrator`), `compute_belief_
outcome_label`/`extract_calibration_examples` (real ground truth:
`World.reflection_notebook` entries settling to `"supported"`/
`"rejected"`), `calibration_gap` (a model-free overconfidence/
underconfidence diagnostic). New `scripts/verify_belief_
calibration.py` (14 checks) — all pass, first run, no bug found. Not
wired into any real consumer this pass — needs a real settled-
hypothesis history this offline environment has no archive to source.

Verified: both new scripts (33 checks total); `verify_b4_tradition_
dormancy.py`/`verify_b4_idea_dormancy.py`/`verify_b0_runtime_
migrations.py`/`verify_task_graph.py`/`verify_scheduler.py`/`verify_
dormancy.py`/`verify_runtime_invariant.py`/`verify_ml_substrate.py`/
`verify_value_model.py` re-run clean; `pyflakes` clean (only the six
known pre-existing forward-ref findings in `engine.py`); `scripts/
verify_replay_hash.py` (4000 ticks, seed 777) — MATCH; `scripts/
verify_native_soak.py` (3 seeds x 3000 ticks) — MATCH.

## [1.34.209] — Part B: B14.2/B14.3's snapshot writer; Tier 6 L2.1 value model

Explicit user instruction: "Continue with B Big Bang progress and also
build parallely something from other tiers." Two independent pieces,
one batch, same pattern as v1.34.207.

Fixes the exact correctness hazard flagged at v1.34.205 FIRST — a
naive diff format would let `_prune_snapshots` orphan an
unreconstructable INCREMENTAL snapshot whose FULL base got pruned —
then builds the real writer on the fixed foundation, not the other
way around.

New `persistence/diff.py`: `diff_dict`/`apply_patch`, a recursive
structural dict diff (nested dicts diffed recursively key by key,
every other value replaced wholesale if changed — a deliberate
list-atomic scope trim over a general list-diff, documented in the
module's own docstring). `persistence/database.py` gained this
project's first-ever schema migration (`_migrate_snapshots_schema`,
`ALTER TABLE snapshots ADD COLUMN kind/base_snapshot_id`, `PRAGMA
table_info`-guarded so it's a real no-op on an already-migrated DB;
existing rows correctly default to `kind='full'`). `save_snapshot`
gained a real `kind` param: `"incremental"` stores a `diff_dict` patch
against the most recent snapshot (degrading to a real full save with
nothing to diff against yet); `_reconstruct_snapshot_dict` walks an
INCREMENTAL chain back to its FULL root and applies every patch
forward, raising `ValueError` on a genuinely missing base rather than
silently half-reconstructing. `_prune_snapshots` now walks every kept
row's `base_snapshot_id` ancestry so a chain's own dependencies can
never be pruned out from under it. `SimulationEngine._tick_once`'s
real periodic snapshot call site now calls `self._snapshot_scheduler.
plan().value` and threads it through — B14.2's `plan()` output is
finally consulted by something real. B14.3's `batch_size_for_storage`
stays unconsulted (still one `INSERT` per snapshot, no batched-write
mechanism to size).

New `scripts/verify_b14_snapshot_diff.py` (20 checks — diff/patch
round-trip under 20,000 randomized trials with a no-mutation
guarantee, a real FULL+INCREMENTAL+INCREMENTAL chain reconstructing
correctly through both `load_latest_snapshot`/`load_snapshot_at_tick`,
a negative control proving the OLD naive prune would have orphaned
the chain against the NEW chain-aware prune which doesn't, the
missing-base `ValueError` case, and backward compatibility with a
genuinely pre-migration row) — all pass, first run, no bug found.

Verified: the new script; `verify_b14_persistence_scheduling.py`/
`verify_task_graph.py`/`verify_scheduler.py`/`verify_dormancy.py`/
`verify_runtime_invariant.py` re-run clean; `pyflakes` clean (only the
six known pre-existing forward-ref findings in `engine.py`); `scripts/
verify_replay_hash.py` (4000 ticks, seed 777) — MATCH; `scripts/
verify_native_soak.py` (3 seeds x 3000 ticks) — MATCH. No native
module or persisted `World` schema touched — the diff format operates
purely on the already-serialized `world_json` blob.

**Tier 6, L2.1 — value/consequence model.** New `hearthmind/ml/
value_model.py`: `ValueConsequenceModel` (sigmoid-output MLP over four
real per-agent structural features, reusing L0's `FeatureEncoder`/
`MLP`/`train_mlp_sgd` directly), `compute_consequence_label` (real
`emergence.magnitude` + a real downstream-life-event bump, additive
and re-clamped, never multiplicative), `rank_by_predicted_value` (the
real B2.4 "attention follows change" consumer — blocked since
v1.34.83 on exactly this — stable-sorted, no RNG). New `scripts/
verify_value_model.py` (16 checks) — all pass, first run, no bug
found. Not wired into any real B2.4/L2.2 call site this pass — needs
real weights trained against a real accumulated emergence-log/
life-events archive this offline environment has no live world to
source, same discipline L0/L3.1/L3.2 shipped under. No native module
or persisted state touched — no replay-hash/native-soak re-run needed
for this half.

## [1.34.208] — Part B: B4.2's third dormancy candidate ("forgotten traditions")

Explicit user instruction: "Continue with B and ship Big Bang progress
not little progress."

New `SimulationEngine._update_tradition_dormancy` (monthly, ON_EVENT/
month_end): the same real `DormancyManager` shape the institutions
(v1.34.187) and ideas (v1.34.204) pilots already proved, applied to
every named settlement's own `Settlement.traditions` entries. Tracks
each `(settlement, tradition)` pair's real personal-keeper count
(`Agent.kept_traditions`) — an unchanged count across 3 consecutive
monthly checks sleeps it, a genuine new keeper wakes it immediately.
`_maybe_spread_tradition_keeping`'s existing per-settlement weighted
pick now excludes sleeping traditions, falling back to the full list
when every tradition a settlement holds is asleep at once. Compliant
with B15's `TWO_PART_GUARANTEE` for the same reason both siblings are:
`Settlement.traditions` itself stays untouched Body-deterministic
state — only which tradition gets the next Mind-layer personal-
keeper-spread roll is gated.

New `scripts/verify_b4_tradition_dormancy.py` (16 checks) — all pass,
first run, no bug found.

Verified: the new script; `verify_b4_idea_dormancy.py`/`verify_b0_
runtime_migrations.py`/`verify_task_graph.py`/`verify_scheduler.py`/
`verify_dormancy.py` re-run clean; a real production-path 4000-tick
LLM-disabled smoke test (agents genuinely picked up kept traditions
over the run, clean round-trip); `scripts/verify_replay_hash.py`
(4000 ticks, seed 777) — MATCH; `scripts/verify_native_soak.py`
(3 seeds x 3000 ticks) — MATCH. `pyflakes` clean.

B4.2's other two candidates (inactive settlements, distant wildlife)
remain open — both touch genuine Body-deterministic per-tick
simulation, unlike the three Mind-layer-only siblings now shipped, and
would need a real lossless elapsed-tick reconstruction to stay B15-
compliant. B9.3 was investigated (most per-tick jobs already gate
correctly via `SimClock`'s own calendar event flags) but not converted
this pass — no obviously-wrong mismatch found without a genuine
per-site read of all ~200 call sites. B10.2 stays confirmed exhausted.
B11/B12/B14.2/B14.3/B15.5 remain open, each needing its own
separately-scoped build.

## [1.34.207] — C++ port: A14's biology-tick scalar math; Tier 6 L3.1 LLM cost regressor

Explicit user follow-up: "Yes and try something from tier 6 as well
and see if some C++ porting backlog can be done."

**C++ porting backlog, module 24.** New `cpp/src/biology_ticks.cpp`
ports A14's five per-agent, per-tick scalar-drift passes
(`Population._tick_sleep_debt`/`_tick_immune_strength`/`_tick_stress`/
`_tick_injury_recovery`/`_tick_development`) — the same "runs for
every agent, every tick, unconditionally, pure arithmetic" shape
`needs.cpp`/`emotion_decay.cpp` already established, left unattempted
since A14 shipped. One shared `BiologyConstants` struct built once per
tick backs all five; each method's own early-out is mirrored inside
the native function so every call site stays uniform. Fallback
(extension unbuilt): the original pure-Python branches, unchanged.

Verified: a 50,000-trial randomized equivalence test against a direct
Python reference of the fallback branch (0 mismatches);
`scripts/verify_native_soak.py`'s new toggle — MATCH on all three
default seeds (1/55/999, 3000 ticks each, full `World.to_dict()` per
tick). `pyflakes` clean.

**Tier 6, L3.1 first instance.** New `hearthmind/ml/llm_cost.py`'s
`LLMCostRegressor`: predicts one specific about-to-be-issued call's
`latency_ms` from its own shape (task/prompt+context size/current
backlog/`deep_reasoning`), distinct from L3.2's already-shipped
aggregate call-volume forecaster. `should_preflight_defer` is the real,
independently-testable decision this model would inform — reliability-
weighted, never a hard block. Not wired into the real scheduling path
this pass (no live archive in this environment to train real weights
against), same discipline L0/L3.2 shipped under.

A real bug was caught and fixed during verification, not shipped:
the first draft's synthetic dataset used raw char counts and
millisecond targets directly, and plain SGD reliably diverged to NaN
(the same bug class CLAUDE.md's own v1.34.174 entry documents). Fixed
by normalizing both input scale (`prompt_chars_k`/`context_chars_k`)
and target scale (`LATENCY_SCALE_MS`), plus a lower default learning
rate (0.001) — documented at the call site.

Verified: `scripts/verify_llm_cost.py` (16 checks) — all pass.
`pyflakes` clean. `scripts/verify_ml_substrate.py`/`verify_
forecasting.py` re-run clean (unaffected).

## [1.34.206] — Part B: B13's UI trigger, plus a real frontend bug caught by live browser testing

Explicit user follow-up: "Build B13 and other items you can complete."
Ships the one remaining B13 gap flagged at v1.34.205: a real dev-
console/HTTP trigger for `_run_llm_concurrency_hypothesis`.

**UI trigger.** New `POST /intervene/llm-concurrency-hypothesis`
(same queued-intervention seam every other `/intervene/*` endpoint
uses) -> `SimulationEngine._maybe_start_llm_concurrency_hypothesis`
-> a real background `asyncio.Task` running v1.34.205's already-
verified probe+equivalence-check mechanism. One request in flight at
a time; a second concurrent request is dropped, not stacked.
`full_diagnostics()['llm_concurrency_hypothesis']` exposes `running`/
`last_result`/`history_recent` (bounded, last 10). New dev-console
panel (`interface/static/index.html`/`app.js`): a proposed-value
input, an optional hypothesis text field, a "Run hypothesis" button
that POSTs then polls `/diagnostics` until the real result lands. New
`scripts/verify_b13_dev_console_endpoint.py` (9 checks, drives the
engine-side `WorldBroadcaster.enqueue_intervention`/`_apply_pending_
interventions` seam directly, no HTTP server needed) — all pass,
first run, no bug found.

**Real bug caught by live browser testing, not the new verify script
above.** That script only exercises engine-side machinery, never the
actual frontend JS, so it structurally could not have caught this. A
live Playwright pass (real dev server, real browser, real click)
found the panel's status text never advanced past "queued…" despite
the backend genuinely completing (confirmed via a direct `curl
/diagnostics` showing a real `decision: "kept"` result). Root cause:
`GET /diagnostics`'s response nests `SimulationEngine.
full_diagnostics()` under a top-level `"engine"` key
(`interface/app.py`'s own response shape), but the new JS read
`report.llm_concurrency_hypothesis` un-nested in two places (the
run-button's own poll loop and the "Full diagnostic report" button's
handler) — both silently `undefined` forever. The identical bug, same
root cause, was found PRE-EXISTING one line above
(`report.pillar_cognition_status`) — that panel's rendering had been
silently broken since it first shipped, fixed in the same pass. A
third dead read (`renderDevConsole`'s `payload.diagnostics.llm_
concurrency_hypothesis`, reading off the periodic WebSocket broadcast
payload) was found and dropped rather than fixed — that field only
ever exists in the heavier `full_diagnostics()` report, never in the
cheap per-tick `_diagnostics_snapshot()` the broadcast carries, so the
read could never have resolved to anything, and the panel already
refreshes correctly via its own explicit poll loop and the "Full
diagnostic report" button.

Re-verified via a second live Playwright pass: the panel now
genuinely resolves to a real result ("kept: measurement improved and
passed the semantic-safety gate... 1 -> 5, 264.2ms -> 61.2ms") within
seconds, and the "Full diagnostic report" button now shows real
non-empty `pillar_cognition_status` content. No JS console errors
beyond an unrelated benign favicon 404.

Standing lesson, worth restating: an engine-level verify script proves
backend machinery is real but cannot catch a frontend read-path bug —
only an actual browser exercising the actual JS can, which is exactly
why "test the UI in a browser before reporting done" is a standing
workflow rule.

Verified: `scripts/verify_b13_dev_console_endpoint.py` (9 checks) —
all pass. `node --check` clean on `app.js`, before and after the three
read-path fixes. Two independent live Playwright passes (pre-fix,
confirming the bug; post-fix, confirming both panels genuinely
populate with real data) via a real dev server, LLM disabled. No
fabricated results at any point — every reported outcome came from an
actual tool/agent execution. `pyflakes` clean on all touched Python
files (only the six known pre-existing forward-ref findings). No
native module, persisted `World` state, or deterministic Body code
path touched — no replay-hash/native-soak re-run needed.

## [1.34.205] — Part B: B13's real first wiring for llm_max_concurrent, B10.2 re-audit

Explicit user follow-up: "Keep going and build whatever is required for
blocked items." Investigated each of B14.204's six flagged-open items
concretely rather than repeating the prior status notes, and shipped
real code for the one that turned out genuinely buildable this pass.

**B13, real first wiring.** `SimulationEngine.__init__` builds a real
`HypothesisLoop` over `llm_max_concurrent`, deliberately MANUAL-only
(never scheduled into `_TICK_JOBS`) so it can never fight B6/B7's own
already-live automatic `BangBangController` over the same tunable. The
item's own "needs a live-diagnostic-driven pass" framing turned out to
hide a sharper structural blocker: `HypothesisLoop.apply_and_measure`'s
`measure_fn` is synchronous and called twice with zero real elapsed
time between calls — unable to host an awaited probe, and this
environment has no live LLM server to measure real call latency
against regardless. Solved with a genuine ACTIVE probe instead:
`_probe_concurrency_wait_ms` drives real asyncio tasks through a
throwaway `_ResizableSemaphore` (the same class `CognitionRunner`
itself uses) and times real queueing wait under a given concurrency
limit — needs no LLM, verified low-concurrency measurably waits longer
than high. `_run_llm_concurrency_hypothesis` awaits this probe twice
(current value, proposed value) BEFORE handing the results to the
still-synchronous, already-verified B13.1 loop unmodified.
`equivalence_check_fn` reuses `simulation/sandbox.py`'s own real fork-
and-tick technique (`World.from_dict`, never `copy.deepcopy`) plus
B15.1's hashing shape — confirms directly, not assumed, that
`llm_max_concurrent` cannot affect Body-deterministic state. New
`scripts/verify_b13_llm_concurrency_hypothesis.py` (8 checks).

**B10.2 re-audit.** Direct line-by-line inspection (not inherited
trust) of every `settlement/buildings.py` flagged site and a
representative `agents/population.py` sample confirmed the fourth
pilot's (v1.34.192) conclusion still holds: every remaining flagged
site either needs the kind-index BUILDER functions themselves or
genuinely filters by `.stage`/`.condition`/`.owner_agent_id` rather
than `.kind`, so the existing `buildings_of_kind`/`vehicles_of_kind`/
`institutions_of_kind` indexes cannot help any of them.

**B14.2/B14.3, real design finding (not code).** Investigated actually
building a diff-based incremental snapshot format and found a real
correctness hazard before writing a line of it: `persistence/
snapshot.py`'s `_prune_snapshots` deletes rows by pure tick recency
with no concept of a FULL+INCREMENTAL dependency chain — a naive
implementation would let an INCREMENTAL row outlive its own base FULL
row, making that snapshot silently unreconstructable. Documented as
the concrete first design constraint (prune whole chains atomically)
rather than rushed past to ship something that looked done.

**B11/B12, B9.3**: investigated for a safe, meaningful, environment-
testable first consumer; none found this pass that wouldn't either
duplicate already-shipped durable-memory mechanisms (B11) or need a
live LLM server this environment doesn't have (a genuine hard blocker,
not a discipline choice). No hand-rolled per-tick cadence site found
warranting a B9.3 TimescaleGate migration beyond what B3 already
migrated. Left open, not forced.

Verified: `scripts/verify_b13_llm_concurrency_hypothesis.py` (8
checks) — all pass, first run, no bug found. `verify_optimization_
hypothesis.py`/`verify_tuning.py`/`verify_b6_adaptive_concurrency.py`/
`verify_b7_hardware_citizenship.py`/`verify_b0_runtime_migrations.py`/
`verify_runtime_invariant.py`/`verify_task_graph.py`/`verify_
scheduler.py`/`verify_b3_dirty_events.py`/`verify_dormancy.py`/
`verify_b4_idea_dormancy.py` re-run clean. A real before/after replay-
hash check (4000 ticks, seed 777, `--in-process`) — MATCH, byte-
identical. `scripts/verify_native_soak.py` (3 seeds x 3000 ticks) —
MATCH. `pyflakes` clean (only the six known pre-existing forward-ref
findings in `engine.py`).

## [1.34.204] — Part B: B4.2's second dormancy candidate ("unused ideas")

Explicit user instruction: "Reverse the 'never big-bang' policy and
complete part B." Investigated what "complete Part B in full" would
actually require across every still-open item (B4.2's four remaining
candidates, B9.3's ~200-site audit, B10.2's 72 flagged sites, B11/B12/
B13's need for a real first consumer each, B14.2/B14.3's need for a
diff/batched-write mechanism that doesn't exist in `persistence/
database.py`, B15.5's need for a real HearthBench runner that doesn't
exist) — several of these need real, separately-scoped infrastructure
invented from scratch (a diff-format snapshot writer, a trained
`WorkloadForecaster`, an actual HearthBench Part A runner) rather than
a wiring pass, and rushing all of them through in one turn would trade
away exactly the correctness discipline this project's "never big-bang"
rule exists to protect — real production simulation state, not a
throwaway prototype. Shipped the one item this turn that's both a
genuine, real behavior change AND fully self-contained: a second B4.2
dormancy candidate.

**"Unused ideas" pilot.** Same real `DormancyManager` sleep/wake shape
as the already-shipped "idle institutions" pilot (v1.34.187), applied
to `World.invented_concepts` still in `proposed`/`spreading` status
instead of institutions. New `SimulationEngine._update_idea_dormancy`
(monthly, `IDEA_DORMANCY_IDLE_CHECKS_THRESHOLD=3`, `_idea_fingerprint`
= status + adopter count): a growing concept with an unchanged
fingerprint across 3 consecutive monthly checks goes DORMANT; a real
adopter gain or status change wakes it immediately.
`_maybe_spread_concepts`'s per-tick adoption-roll list now excludes
sleeping ideas, falling back to the full list if every growing concept
happens to be asleep at once — same "dormancy narrows attention, never
silently disables the job" fallback shape `_institution_job_target`
already established.

Compliant with B15's `TWO_PART_GUARANTEE` for the identical reason the
institutions pilot is: this only narrows Mind-layer per-tick attention
(which concept gets a chance at gaining an adopter this specific tick)
— a concept's own eventual adoption/established/abandoned/retired fate
is completely untouched, only the cadence of attempts along the way.
The other three named B4.2 candidates (forgotten traditions, inactive
settlements, distant wildlife) genuinely differ: each would need to
sleep a real Body-deterministic per-tick draw (wildlife movement/
reproduction, settlement decay) and reconstruct it losslessly on wake
to stay Constitution-compliant — real, materially larger work, still
flagged, not attempted this pass.

New `SimulationEngine._runtime_registry_idea_dormancy`/`_runtime_
scheduler_idea_dormancy`: registered via the same B0.3/B3 `ON_EVENT`/
`month_end` machinery as `_update_institution_dormancy`, migrated onto
the real B1/B2/B3 runtime from the moment it shipped rather than
starting as a plain direct call and needing a second migration pass
later.

New `scripts/verify_b4_idea_dormancy.py` (14 checks, standalone, no
unittest) — all pass, first run except two fixture bugs caught before
shipping (a missing `tick_invented`/`inventor_agent_id` on the test's
own `InventedConcept` construction, and the final dispatch check
needing the real `Scheduler.event_bus.publish`/`run_tick()` call
rather than a bare `_tick_once()`, which needs a running asyncio event
loop this synchronous script doesn't have).

Verified: `scripts/verify_b4_idea_dormancy.py` (14 checks) — all pass.
`verify_b0_runtime_migrations.py`/`verify_b3_dirty_events.py`/`verify_
dormancy.py`/`verify_runtime_invariant.py`/`verify_task_graph.py`/
`verify_scheduler.py` re-run clean. A real before/after replay-hash
check (4000 ticks, seed 777, `--in-process`) — MATCH, byte-identical.
`scripts/verify_native_soak.py` (3 seeds x 3000 ticks) — MATCH.
`pyflakes` clean on all touched files (only the six known pre-existing
forward-ref findings in `engine.py`).

**Honest scope of "complete Part B," left open**: B4.2's remaining
three candidates; B9.3's full ~200-site timescale audit; B10.2's 72
`scan_global_scans.py`-flagged sites (a fresh re-run this pass found
the same shape as every prior triage: the `agents/population.py`
majority are either already-covered `.agents` scans or need every
agent regardless of kind, and the `world/` sites are CA/terrain
kernels needing every tile by construction — genuinely not more
index-swap material, the same conclusion the fourth B10.2 pilot
reached); B11/B12/B13 (each needs a real first consumer or trained
instance that doesn't exist yet); B14.2/B14.3 (no diff/batched-write
mechanism exists in `persistence/database.py` to consult); B15.5 (no
real HearthBench runner exists to request a pinned profile from). None
of these six is a wiring pass over already-real machinery the way this
turn's item was — each needs its own separately-scoped design/build
effort, continuing in future turns rather than compressed into this
one at the cost of correctness review.

## [1.34.203] — Part B: B14.1 + B15.3/B15.4 wired, B1's stale header corrected

Explicit user instruction: "Continue B and try closing it this turn so
build as many items as possible." Two more real control-point wirings
in one batch, plus a docs-only correction that closes a third item
outright.

**B1 corrected from PARTIAL to SHIPPED (docs-only).** B1's own header
had read "not yet wired into the live tick loop" since v1.34.162 —
stale since v1.34.197, when B0.3's migration fully closed and every
one of the 56 real `_TICK_JOBS` entries started running through a
real `TaskRegistry`+`Scheduler` pair built from B1's own `Task`/
`topological_order` machinery. No code changed; the doc simply hadn't
caught up.

**B14.1 (Scheduled, budgeted, idle-preferring snapshotting) wired.**
`SimulationEngine.__init__` now builds a real `SnapshotScheduler`
(`self._snapshot_scheduler`) — `max_interval_ticks = config.snapshot_
every_ticks` (the exact prior worst-case durability guarantee,
UNCHANGED) and `min_interval_ticks = snapshot_every_ticks // 2` (a
genuine opportunistic tightening, reusing the same real daily `is_
quiet_window`/backlog-history signal B7.2/B8.4 already wired last
pass). `_tick_once`'s old flat `_ticks_since_snapshot >= snapshot_
every_ticks` counter is gone, replaced by a real `self._snapshot_
scheduler.due(tick, backlog_samples, capacity)` call. B14.2's
FULL/INCREMENTAL kind selection is deliberately NOT consulted —
`save_snapshot` has no real diff/incremental-write mechanism to hand
a planned kind to, so calling `plan()` would be decorative, not real.

New `scripts/verify_b14_persistence_scheduling.py` (8 checks): the
real policy an engine builds matches `config.snapshot_every_ticks`
exactly on the (unchanged) max bound and is genuinely tighter on the
min; a genuinely BUSY backlog history never snapshots before the old
hard ceiling; a genuinely QUIET one snapshots as early as the new
tighter floor; the "first check never fires" contract holds through
the real `_tick_once` path; the real `snapshots` table row count
matches the engine's own counter (accounting for the pre-existing
genesis snapshot `load_or_create` already writes at construction).

**B15.3/B15.4 (the escalation ladder + cognition budget) wired,
deliberately narrow.** This NEVER touches the real existing `llm_
pressure` slowdown/pause mechanism — CLAUDE.md's "Preserve absolutely"
names that real-time tick-pacing mechanism explicitly, and it stays
completely untouched. New `SimulationEngine._maybe_advance_escalation_
ladder` (daily) observes `llm_pressure_ratio() >= LLM_PRESSURE_
SLOWDOWN_START_RATIO` — the exact threshold the untouched pacing
mechanism already treats as "pressure begins here," so the two agree
on what counts as pressure without one driving the other.
`cognition_budget_for_rung` is recomputed daily and cached; `_schedule_
due_cognition`'s own per-tick `use_llm` gate now also requires
`llm_cognition_calls_this_tick < self._cognition_budget.count` — a
genuine no-op at every rung except sustained rung-5 pressure
(`ESCALATION_COGNITION_BASE_BUDGET = 1,000,000`, unreachable by any
real due list), a real cap at rung 5 (`ESCALATION_COGNITION_REDUCED_
BUDGET = 3`). WHICH agents fill whatever budget remains stays entirely
`due_for_cognition`'s own staggered-slot/significance ordering — the
counter only ever says how many, never who, per B15.4's own "never a
selection" guarantee. `full_diagnostics()['escalation_ladder']`
surfaces the real current rung, streak, live budget, `is_reduced`, and
bounded transition history — the real "UI indicator for rung 5...
never silent" B15.3's own text asked for.

New `scripts/verify_b15_escalation_ladder.py` (17 checks): the daily
job only fires through the real `_TICK_JOBS` dispatch on `day_end`,
never a synthetic call; sustained pressure escalates the real ladder
one rung at a time up to rung 5 and only then reduces the real budget;
clearing pressure de-escalates and restores it; an unbounded budget
lets every genuinely-eligible core-cast agent in one tick's due list
get a real (mocked) LLM call scheduled; a reduced rung-5 budget caps
it exactly, with the rest correctly falling back to the deterministic
path rather than being silently dropped; the shared pressure threshold
is exact at the boundary. One real test-isolation fix needed during
verification: the "unbounded budget" scenario initially undercounted
because B2's own independent concurrency-derived backpressure ceiling
(a genuinely separate real gate, unrelated to this pass) was also
active in the test's default config — fixed by mocking `_current_
backpressure_limit` for that one scenario, isolating the B15.4 cap
being tested from B2's own already-verified gate.

**What's still open in Part B, honestly**: B4.2 (four remaining named
candidates — forgotten traditions, inactive settlements, distant
wildlife, unused ideas — each needs a real lossless elapsed-tick
reconstruction to stay B15's own `TWO_PART_GUARANTEE`-compliant, not
attempted this pass); B9.3 (a real audit of ~200 per-tick call sites
for timescale mismatch — genuinely large, not attempted); B10.2 (72
of ~89 flagged sites remain unconverted past the four existing pilot
conversions); B11/B12/B13 (Hierarchical memory, History compression,
Optimization hypotheses — each still needs a real first consumer/
trained-loop instance, none exists yet); B14.2/B14.3 (no real
diff-format/batched-write mechanism exists to consult); B15.5
(`reference_mode` unused in production — no HearthBench runner exists
yet to request a pinned profile). None of these was rushed through
this pass — each genuinely needs either a larger design decision or a
real live-diagnostic-driven judgment call this project's own "never
big-bang" discipline reserves for its own turn.

Verified: `scripts/verify_b14_persistence_scheduling.py` (8 checks)/
`scripts/verify_b15_escalation_ladder.py` (17 checks) — all pass,
first run except the one test-isolation fix noted above (a bug in the
verify script itself, not the module under test). `verify_task_
graph.py`/`verify_scheduler.py`/`verify_runtime_invariant.py`/
`verify_b0_runtime_migrations.py`/`verify_tuning.py`/`verify_b6_
adaptive_concurrency.py`/`verify_b2_broadcast_budget.py`/`verify_b3_
dirty_events.py`/`verify_dormancy.py`/`verify_runtime_diagnostics.py`/
`verify_hardware_profile.py`/`verify_b7_hardware_citizenship.py`/
`verify_b8_predictive_scheduling.py` re-run clean. A real before/after
replay-hash check (4000 ticks, seed 777, `--in-process`) — MATCH,
byte-identical. `scripts/verify_native_soak.py` (3 seeds x 3000
ticks) — MATCH. `pyflakes` clean on all touched files (only the six
known pre-existing forward-ref findings in `engine.py`).

## [1.34.202] — Part B: B8.4 wired + B7.2/B7.3's own flagged gaps closed

Explicit user follow-up: "B8 and MachineProfile persistence and
select_strategy's output still have no real call site — flagged for
later" — picking up my own "Known Issues" note from the B7 turn
(v1.34.201) and closing it, plus B8 (Predictive scheduling), in one
batch.

**MachineProfile persistence (B7.2).** `SimulationEngine.__init__`
now loads a real, host-fingerprinted `MachineProfile` from a file next
to `Config.db_path` (new `_machine_profile_path_for`, `None` for a
`:memory:` db path — kept in-RAM only for that process's lifetime,
never touches disk, never crashes) via a new `_load_or_create_
machine_profile` that degrades a missing, corrupted, or unsupported-
`schema_version` file to a fresh profile rather than crashing startup
— a bad profile file must never be able to take down a real
deployment, same discipline `HostProbe.sample()` itself already holds
to. Records a real session at construction. A new monthly `_maybe_
refresh_machine_profile` runs the real storage micro-benchmark
(`HostProbe.sample(run_storage_bench=True)`, deliberately NOT the
daily check's own `run_storage_bench=False` reading — a few ms of
real disk I/O the daily check explicitly skips as needless), folds it
into the profile's EMA, and saves back to disk — the profile now
genuinely "gradually evolves... not resets each time" across a real
restart, per B7.2's own original design text, verified directly (a
second `SimulationEngine` constructed against the SAME db path loads
exactly what the first one saved, `sessions_recorded` incrementing
correctly across both).

**select_strategy's output (B7.3).** `_maybe_tune_llm_concurrency`
(already B6/B7.4's real control point) now also consults `select_
strategy(probe, self._machine_profile)` — the SAME probe already
sampled that call, never a second one — as a THIRD real signal: a
downward-only cap on top of B6's latency-driven step and B7.4's live-
pressure veto, gated to `after > before` (mirroring the host-pressure
veto's own `after >= before` gating) so it only ever intervenes on a
fresh latency-driven INCREASE, never forcing down an already-stable
value sitting above the hint — a human retune or CLI override still
always wins going forward, exactly the promise this method's own
opening docstring already makes for the host-pressure veto. Logged
with `strategy_cap_applied: True`, distinct from `host_pressure_veto`.
Verified directly: modest hardware's hint genuinely caps a would-be
latency-driven climb independent of any live host-pressure veto; a
real-hardware probe's hint does NOT needlessly clamp an ordinary
healthy step that stays within it.

**B8.4 — Idle-window scheduling, wired.** `_maybe_tune_llm_
concurrency` now samples `self._cognition_runner.backlog` into a
bounded daily history (new `self._recent_llm_backlog_samples`,
`RECENT_LLM_BACKLOG_SAMPLES_MAX=30`) on EVERY call — including the two
cases the method itself goes on to skip (LLM disabled, under-
evidenced), since those are exactly the cases where "load has stayed
low" is both most likely true and most useful to know, verified
directly. `_maybe_refresh_machine_profile`'s own real storage-
benchmark disk I/O only runs once `is_quiet_window` reads that history
as genuinely quiet — B8.4's own stated purpose ("schedule expensive
maintenance... into predicted-quiet periods") applied to this exact
kind of work for the first time — verified directly: a busy backlog
history skips the benchmark entirely, a quiet one runs exactly one
real call asking for the actual micro-benchmark. **B8.1-B8.3 remain
explicitly unwired** — `plan_reservation`/`ForecastAccuracyTracker`
both depend on B8.1's `WorkloadForecaster` producing a real trained
prediction first, and training one for real needs a real recorder
archive this pass had no reason to fabricate (same "no fine-tuning run
itself is implemented" scope trim this project's own FT items already
used) — flagged as real future work, not forced through dishonestly.

`full_diagnostics()['machine_profile']` surfaces the real persisted
profile (host_fingerprint/sessions_recorded/storage benchmark EMA/
whether it's actually persisted-to-disk), the most recent `select_
strategy` verdict (honestly `None` before any real call), and the live
`is_quiet_window` reading — verified directly.

**A real regression caught and fixed before shipping, not left for
later**: wiring `select_strategy`'s cap in unconditionally (my first
draft) broke two pre-existing, previously-green scripts (`verify_b6_
adaptive_concurrency.py`, `verify_b7_hardware_citizenship.py`) —
`select_strategy`'s own formula tops out at a hint of 3 regardless of
how capable the probed hardware is, so an unconditional cap silently
made `llm_max_concurrent`'s registered [1,8] legal range effectively
[1,3] for every host, and even a "true no-op" scenario (latency inside
the dead zone, nothing should change) got force-adjusted down whenever
the starting value already sat above 3. Root-caused to the cap
applying even when no real change was in progress; fixed with the
`after > before` gating described above, then `verify_b6_adaptive_
concurrency.py` (whose own scenarios deliberately move `llm_max_
concurrent` up to 4/6, above `select_strategy`'s own ceiling) was
given a companion fix — it patches `select_strategy` to a permissive
stand-in for its own duration, so it keeps proving B6's bang-bang
mechanics in isolation rather than re-measuring B7.3's real
interaction, which the two scripts below already cover.

New `scripts/verify_b8_predictive_scheduling.py` (25 checks): profile
persistence across two real engine constructions against the same db
path, `:memory:` never touching disk, a corrupted profile file
degrading rather than crashing, the strategy cap firing/not-firing
correctly in both directions with the real semaphore/backpressure
state reflecting it, the daily backlog sample firing under both skip
conditions, the quiet-window gate on the real monthly refresh (busy
skips, quiet runs exactly once with the right benchmark kind), and
`full_diagnostics()` surfacing real state including the honest
pre-first-call `None`.

Verified: `scripts/verify_b8_predictive_scheduling.py` (25 checks) —
all pass, first run, no bug found in the module under test (the one
real bug found — the cap's `after > before` gating — was caught and
fixed in `engine.py` before this script was even written, via the
pre-existing `verify_b6_adaptive_concurrency.py`/`verify_b7_hardware_
citizenship.py` regressions it caused). `verify_task_graph.py`/
`verify_scheduler.py`/`verify_runtime_invariant.py`/`verify_b0_
runtime_migrations.py`/`verify_tuning.py`/`verify_b6_adaptive_
concurrency.py` (updated)/`verify_b2_broadcast_budget.py`/`verify_b3_
dirty_events.py`/`verify_dormancy.py`/`verify_runtime_diagnostics.py`/
`verify_hardware_profile.py`/`verify_b7_hardware_citizenship.py`
re-run clean. A real before/after replay-hash check (4000 ticks, seed
777, `--in-process`) — MATCH, byte-identical (expected: every touched
code path is inert while the LLM is disabled). `scripts/verify_
native_soak.py` (3 seeds x 3000 ticks) — MATCH. `pyflakes` clean on
all touched files (only the six known pre-existing forward-ref
findings in `engine.py`).

## [1.34.201] — Part B: B7 (Hardware model) wired to a real control point + host-probe diagnostics

Explicit user follow-up ("B7 and cheap next tier item"), continuing
the Part-B closing sequence (B6 v1.34.198, B2 v1.34.199, B3 v1.34.200).
B7.1-B7.4 (`simulation/hardware_profile.py`: `HostProbe`/
`MachineProfile`/`select_strategy`/`GoodCitizenPolicy`) were real,
verified pure functions since v1.34.173, but had zero real call sites
— B7.4's own docstring named exactly this gap: "'lower priority for
background work' itself needs a real scheduler to lower priority IN
— that's B2's job... `should_back_off` is the input signal such a
scheduler would consult, not the mechanism."

Now that B6's `_maybe_tune_llm_concurrency` is a real, live scheduler,
it is exactly that consumer. A real `HostProbe.sample(run_storage_
bench=False)` reading (storage micro-benchmark skipped — irrelevant to
citizenship, needless disk I/O on a check that runs at most once a
day) is taken every call the method doesn't skip; `GoodCitizenPolicy.
should_back_off` (BALANCED aggressiveness) acts as a DOWNWARD-ONLY
veto layered on top of the existing latency-driven `BangBangController`
decision — it can force a step down (or cancel an unwanted step up)
that latency alone wouldn't have produced, but never blocks or
reverses a decrease latency itself already decided (a struggling host
and a struggling LLM are two independent reasons to ease off, neither
overrides the other's own decrease).

Verified via direct scenario tests using the real `Scheduler`/
`GoodCitizenPolicy`/`HostProbe` classes (a mocked `HostProbe.sample`,
not a mocked policy or controller): a healthy host + latency inside
the hysteresis dead zone stays a genuine no-op, nothing logged; a
pressured host under otherwise-identical conditions forces a real,
logged one-step decrease (`host_pressure_veto: True`); a pressured
host doesn't double-step a latency-driven decrease already in
progress; a pressured host cancels (not amplifies) an unwanted
latency-driven increase, landing back at the starting value with no
logged change (a real, deliberate design choice — "only log real
changes" holds here too, not a bug); the LLM-disabled path never
samples `HostProbe` at all.

**Bonus, same batch ("cheap next tier intel")**: the real `HostProbe`
reading is now cached and surfaced via `full_diagnostics()
['host_probe']` (every field + the real `should_back_off` verdict +
the tick it was sampled at — honestly `None` before any real sample
has happened, never a fabricated placeholder). Sampling was
restructured to run unconditionally whenever the method isn't skipped
(not only when a veto might apply), so this diagnostic always reflects
a fresh reading — still at most once a day, no new per-tick cost.

New `scripts/verify_b7_hardware_citizenship.py` (14 checks).

Verified: `scripts/verify_b7_hardware_citizenship.py` (14 checks) —
all pass, first run, no bug found (one test-design bug caught and
fixed in the SCRIPT itself, not the module under test: two scenarios
had the BangBangController's increase/decrease polarity backwards —
raising `llm_max_concurrent` plausibly RAISES measured latency toward
target, so latency far ABOVE target drives a decrease and latency far
BELOW target drives an increase, the opposite of the first draft's
assumption). `verify_task_graph.py`/`verify_scheduler.py`/`verify_
runtime_invariant.py`/`verify_b0_runtime_migrations.py`/`verify_
tuning.py`/`verify_b6_adaptive_concurrency.py`/`verify_b2_broadcast_
budget.py`/`verify_b3_dirty_events.py`/`verify_dormancy.py`/`verify_
runtime_diagnostics.py`/`verify_hardware_profile.py` re-run clean. A
real before/after replay-hash check (4000 ticks, seed 777,
`--in-process`) — MATCH, byte-identical (expected: every touched code
path is inert while the LLM is disabled). `scripts/verify_native_
soak.py` (3 seeds x 3000 ticks) — MATCH. `pyflakes` clean on all
touched files (only the six known pre-existing forward-ref findings
in `engine.py`).

## [1.34.200] — Part B: B3 (Event-driven execution) wired to a real control point + B5.3 diagnostics wiring

Explicit user follow-up ("B3 and build some cheap next tier intel as
well"), continuing the same Part-B closing sequence (B6 v1.34.198, B2
v1.34.199). B3.1 (`DirtyTracker`)/B3.2 (`EventBus`) were already real,
verified machinery (`simulation/reactivity.py`, v1.34.165) but had
never been given a real production `ON_DIRTY`/`ON_EVENT` task to act
on — every one of B0.3's 56 migrated jobs is `PriorityClass.PERIODIC`
(always due).

`_update_institution_dormancy`'s own pre-migration body was already a
pure `if "month_end" not in events: return` guard with no other logic
ahead of it — exactly B3.2's own named shape (a discrete "did this
happen" signal, distinct from `_maybe_tick_trigger_state_edges`'s
ongoing-state edge detection). Its Task is now declared `TriggerKind.
ON_EVENT`/`event_types={"month_end"}` instead of `PERIODIC`, moving
that guard OUT of the function body and INTO the scheduler's own
`_due_and_reason` gate — a real `skipped_clean` (never touching
budget/deferral machinery) on every non-month_end tick instead of the
function being called and immediately returning. `_tick_once`
publishes `"month_end"` into this specific scheduler's real `EventBus`
right after `events` is computed, the same source the old internal
guard read from directly. The function's own signature dropped its now
-redundant `events` param; its `_TICK_JOBS` entry moved from
`_JOB_EVENTS` to `_JOB_NO_ARGS` to match.

Verified via a real 3,200-tick drive (not a synthetic scenario): the
job ran on EXACTLY the real month_end ticks crossed, never more or
fewer; `TaskMetrics.skipped_clean_count` accounts for every other tick
(a genuine skip, not merely a fast internal return); a control run
with nothing ever published to the EventBus confirmed the gate is
real (never fires without a publish); and the real `_tick_once()` call
site itself (not just a direct scheduler drive) fires the job on a
genuine month_end.

**Bonus, same batch ("cheap next tier intel")**: B5.3's `runtime_
diagnostics_report` (built v1.34.183, never wired to a real HTTP/
diagnostics surface for lack of a real subsystem running through
`Scheduler` to expose — no longer true after B0.3/B2/B3) is now wired
into `full_diagnostics()['runtime_diagnostics']['institution_
dormancy']`, reading the real, live `institution_dormancy` scheduler
built this same pass — the first genuinely production (not synthetic-
task) reading through that report function. Deliberately scoped to one
representative scheduler rather than an aggregate across all ~57 real
per-job schedulers (flagged future work, not guessed at) — cheap
because it's pure read-only composition of already-existing real data.

New `scripts/verify_b3_dirty_events.py` (16 checks). `scripts/verify_
b0_runtime_migrations.py` updated: its generic MIGRATIONS-driven
"every job is CRITICAL+PERIODIC, always runs every tick" assertions
now special-case `institution_dormancy` (a genuinely different,
correct behavior by design) via a new `EVENT_DRIVEN_TASK_IDS` set,
rather than silently going stale.

Verified: `scripts/verify_b3_dirty_events.py` (16 checks) — all pass,
first run, no bug found. `verify_task_graph.py`/`verify_scheduler.py`/
`verify_runtime_invariant.py`/`verify_b0_runtime_migrations.py`
(updated for the one now-ON_EVENT job)/`verify_tuning.py`/`verify_b6_
adaptive_concurrency.py`/`verify_b2_broadcast_budget.py`/`verify_
dormancy.py`/`verify_runtime_diagnostics.py` re-run clean. A real
before/after replay-hash check (4000 ticks, seed 777, `--in-process`)
— MATCH, byte-identical. `scripts/verify_native_soak.py` (3 seeds x
3000 ticks) — MATCH. `pyflakes` clean on all touched files (only the
six known pre-existing forward-ref findings in `engine.py`).

## [1.34.199] — Part B: B2 (Budgets & scheduling) wired to a real control point

Explicit user follow-up ("B2"), continuing the same Part-B closing
sequence B6 started (v1.34.198). B2's own machinery (`simulation/
scheduler.py`) was already genuinely imported and running real code
via B0.3's 56 migrated jobs — a stale doc claim that no import from
it existed was wrong — but every one of those jobs is declared
`PriorityClass.CRITICAL` (deliberately, to reproduce "always runs
every tick" pre-migration behavior), and CRITICAL bypasses the
budget/deferral machinery entirely by definition. So B2's actual
distinguishing logic had zero real exercise anywhere.

Presented two design options in text (a genuinely new judgment call,
not a mechanical sweep, per the standing "ask when stuck" workflow
rule): downgrade an existing CRITICAL job (a real behavior change to
already-shipped scheduling) or find a new, genuinely non-critical
control point. User chose the latter, approving `_maybe_broadcast`
(the per-tick WebSocket payload build) as the concrete target.
`_maybe_broadcast` is explicitly cosmetic (agents/buildings/summary
for the live UI) and genuinely safe to lag a tick under load — a
skipped broadcast just means the client gets the next available
frame — unlike every CRITICAL migration, which all touch state a
skipped tick would actually change.

New `BROADCAST_SUBSYSTEM_BUDGET_SECONDS = 0.015` (engine.py), sized
from a direct measurement in this environment, not guessed: a
60-population, 64x64-tile world's real non-idle `_maybe_broadcast()`
call (client_count forced >0 to skip the idle-world fast path) showed
p50 ~9.5ms, max ~40ms over 30 calls. `_maybe_broadcast` now runs
through its own dedicated `TaskRegistry`/`Scheduler` pair (same
one-job-per-registry discipline as every B0.3 migration, avoiding the
double-execution bug class a shared registry would risk) as a real
`PriorityClass.DEFERRABLE` task with a real `SubsystemBudget`,
declared and called separately from the `_TICK_JOBS`/`_RUNTIME_
SCHEDULED_JOB_SCHEDULERS` dispatch table — `_maybe_broadcast` has a
SECOND call site (the real-time `run_forever` llama-server-restart-
edge polling loop, outside `_tick_once` entirely) that must stay a
direct call, confirmed still untouched.

**A real, verified-not-assumed finding, not glossed over**: under the
dedicated-single-task-registry-called-once-per-real-tick pattern
every B0.3 migration uses, `Scheduler.run_tick()` resets `Subsystem
Budget.consumed_this_tick` to 0 at the END of every call — so a solo
task's budget is always full again by the time the NEXT call's
due-check runs, and it therefore ALWAYS runs (never `deferred`, never
`promoted`), regardless of declared priority class. Confirmed via a
direct synthetic test (an artificially-slow task run 6 times against
a tight budget, using the real `Scheduler`/`SubsystemBudget` classes)
before writing any docstring claiming otherwise — a first draft of
`BROADCAST_SUBSYSTEM_BUDGET_SECONDS`'s docstring wrongly claimed
deferral would fire under load; caught and rewritten to state the
verified truth instead. DEFERRABLE is still the semantically honest
declaration (this job genuinely is safe to lag), and what IS real:
`SubsystemBudget.debt_seconds` genuinely and permanently accrues
whenever a call overruns its budget — the first live signal of its
kind for this job, surfaced via a new `full_diagnostics()`
`broadcast_scheduler` key (`budget_debt_seconds` + per-task metrics).
Making deferral itself fire for a real solo per-tick job would need
either a second task sharing this subsystem's budget within the same
`run_tick()` call, or a genuinely different redesign where budget
state persists across calls instead of resetting each one — flagged
as real future work, not silently glossed over.

New `scripts/verify_b2_broadcast_budget.py` (16 checks): the real
task's declaration (DEFERRABLE not CRITICAL, PERIODIC, its own
dedicated registry, the real bound method), the real budget object
matching the documented constant, a cheap real `_maybe_broadcast`
call running with zero debt, the honest never-defers finding proven
directly against the real `Scheduler`/`SubsystemBudget` machinery
(not a mock), overrun debt genuinely accruing and surfacing via
`all_budgets()`, the real `_tick_once` re-raise-on-error pattern
preserved, a real `_tick_once()` call actually routing through the
new scheduler (metrics increment), and confirmation via source
inspection that exactly one direct `self._maybe_broadcast()` call
site remains (the untouched real-time polling one).

Verified: `scripts/verify_b2_broadcast_budget.py` (16 checks) — all
pass, first run except one design correction caught before shipping
(the docstring's initial false "can still overrun and defer" claim,
rewritten after direct measurement disproved it — see above).
`verify_task_graph.py`/`verify_scheduler.py`/`verify_runtime_
invariant.py`/`verify_b0_runtime_migrations.py`/`verify_tuning.py`/
`verify_b6_adaptive_concurrency.py` re-run clean. A real before/after
replay-hash check (4000 ticks, seed 777, `--in-process`) — MATCH,
byte-identical (expected: broadcast is wall-clock-driven and never
touches `World` state). `scripts/verify_native_soak.py` (3 seeds x
3000 ticks) — MATCH. `pyflakes` clean on both touched files (only the
six known pre-existing forward-ref findings in `engine.py`).

## [1.34.198] — Part B: B6 adaptive tuning wired to a real control point

Explicit user follow-up: "Any other remaining items from part B of
tier 5? If so, close them too" -> `AskUserQuestion` chose **B6
adaptive tuning** among several flagged "shipped as a standalone
module, not wired into any real control point" items.

`Config.llm_max_concurrent` — the constant CLAUDE.md's own long
documented history shows being manually re-tuned from live diagnostic
reads across many deployments (4 -> 2 -> 1 -> 2 -> 1 -> 2) — is now
adaptively steered from the same real signal (measured p95 call
latency) via a real `BangBangController` against a real
`TunableRegistry` (`simulation/tuning.py`, both already built at
v1.34.168 but never wired). `SimulationEngine._maybe_tune_llm_
concurrency` (engine.py) runs once a day (staggered with every other
`day_end` check), gated on the LLM being enabled and a minimum
evidence floor, and — once genuinely due — calls a new `Cognition
Runner.resize_concurrency()` (llm/jobs.py) that live-resizes the
ACTUAL concurrency gate in-flight LLM calls run through via a new
`_ResizableSemaphore`: growing releases new permits immediately,
shrinking swallows that many future releases instead of forcibly
reclaiming a permit already held, so an in-flight call is never
interrupted.

Deliberately scoped narrower than a full B13-sandboxed change:
`llm_max_concurrent` only changes LLM call timing/scheduling, never
deterministic `World` state — determinism/reproducibility is
explicitly not a project requirement for LLM-related paths, and every
past manual retune of this exact constant was likewise never gated
behind a replay-hash check. Anti-chatter discipline: `BangBang
Controller`'s own hysteresis dead-zone (target = `ADAPTIVE_LATENCY_
ELEVATED_MS`, the same "healthy ceiling" `_current_backpressure_
limit` already uses — one shared definition of "comfortable," not
two independently-tuned numbers), a once-a-day cadence, a minimum-
evidence floor, and the registered `Tunable`'s own bounded ±1 step
together bound how much and how often this can move. Every real
change (never a no-op) is logged to a new bounded `SimulationEngine.
_adaptive_tuning_log`, surfaced via `full_diagnostics()`'s new
`adaptive_tuning_log_recent`; `_diagnostics_snapshot()`'s `llm_max_
concurrent` now reports the LIVE value (a new `llm_max_concurrent_
static_default` key keeps the frozen startup default visible too).

New `scripts/verify_b6_adaptive_concurrency.py` (21 checks): the
resizable semaphore's grow/shrink correctness under real concurrent
`asyncio` tasks (incl. the load-bearing case — shrinking while
permits are held never disrupts the holder), `_maybe_tune_llm_
concurrency`'s real gates (disabled/insufficient-evidence -> no-op),
a genuine severe-latency reading lowering live concurrency and
actually resizing the real semaphore, a healthy reading raising it
back, the hysteresis dead-zone as a genuine no-op, the bounded floor
holding under repeated severe readings, diagnostics surfacing, and a
CLI-overridden `config.llm_max_concurrent` being respected as the
controller's real starting point (not `tuning.py`'s own hardcoded
default of 2).

Verified: `scripts/verify_b6_adaptive_concurrency.py` (21 checks) —
all pass, first run, no bug found. `scripts/verify_tuning.py` (6
checks) re-run clean. `scripts/verify_b0_runtime_migrations.py` (175
checks)/`verify_task_graph.py`/`verify_scheduler.py`/`verify_
runtime_invariant.py` re-run clean (unaffected). A real before/after
`World.to_dict()` replay-hash check (4000 ticks, seed 777) — MATCH,
byte-identical. `scripts/verify_native_soak.py` (3 seeds x 3000
ticks) — MATCH. `pyflakes` clean on all three touched files (only
the six known pre-existing forward-ref findings in `engine.py`).

## [1.34.197] — Part B: B0.3 closed — every remaining job migrated

Explicit user follow-up: "Choose 1" (extend the Task/Scheduler runtime
to unblock the `_JOB_EVENTS`/`_JOB_EVENTS_SEASON` majority flagged as
blocked after v1.34.196).

**Corrects a wrong claim from v1.34.196's own changelog entry**: no
design change was actually needed. `Scheduler.run_tick(*args,
**kwargs)` already forwards positional arguments straight through to
`task.fn(*args, **kwargs)` (`scheduler.py`) — since every migrated job
holds its own single-task registry, calling `run_tick(events)`/
`run_tick(events, previous_season)` at the real `_tick_once` call site
reproduces the exact prior `method(events)`/`method(events,
previous_season)` call shape with zero `Task`/`Scheduler` change. The
"blocker" was a misreading, not a real limitation — corrected here
rather than left standing.

All 42 remaining `_JOB_EVENTS` jobs plus the 1 `_JOB_EVENTS_SEASON`
job (`_maybe_schedule_chronicle`) migrated in one batch, same
per-job-dedicated-registry shape as every prior migration:
`_maybe_schedule_documentary`, `_maybe_schedule_tradition`, `_maybe_
schedule_folklore`, `_maybe_schedule_legend_detection`, `_maybe_
schedule_invention`, `_maybe_schedule_ontology_proposal`, `_maybe_
schedule_ontology_evolution`, `_maybe_schedule_composite_entity`,
`_maybe_schedule_nature_mind`, `_maybe_schedule_species_variant`,
`_maybe_schedule_rule_proposal`, `_maybe_schedule_composite_reaction_
propose`, `_maybe_schedule_festival`, `_maybe_schedule_religion`,
`_maybe_schedule_narrative_direction`, `_maybe_schedule_culture_
digest`, `_maybe_schedule_consciousness`, `_maybe_schedule_
reflection`, `_maybe_schedule_self_tuning`, `_maybe_schedule_musing`,
`_maybe_schedule_caravan`, `_maybe_schedule_town_brain`, `_maybe_
schedule_beliefs`, `_maybe_schedule_personal_belief`, `_maybe_
schedule_dream`, `_maybe_schedule_memory_drift`, `_maybe_tick_
temperament`, `_maybe_schedule_omen`, `_maybe_tick_market_prices`,
`_maybe_tick_settlement_trade`, `_maybe_pillar_initiates_contact`,
`_maybe_schedule_guild_founding`, `_maybe_schedule_faction`, `_maybe_
schedule_institution_belief`, `_maybe_schedule_geography`, `_maybe_
schedule_fission`, `_maybe_schedule_diplomacy`, `_maybe_schedule_
laws`, `_maybe_schedule_noncore_nudge`, `_maybe_schedule_letter`,
`_update_institution_dormancy`, `_maybe_schedule_institution_culture`,
plus `_maybe_schedule_chronicle`. `_tick_once`'s dispatch loop now
branches on `arg_kind` when a job is runtime-scheduled, calling
`run_tick()`/`run_tick(events)`/`run_tick(events, previous_season)`
as appropriate — the same three-way branch the pre-migration direct
call already had, just routed through each job's own scheduler.

`scripts/verify_b0_runtime_migrations.py`'s `MIGRATIONS` table now
covers all 56 jobs (every real `_TICK_JOBS` entry) with `arg_kind`
threaded through every check — 175 checks total, plus two new checks
(7/8) proving error propagation for both the one-arg (`_JOB_EVENTS`)
and two-arg (`_JOB_EVENTS_SEASON`) shapes specifically, not just the
zero-arg shape the prior batches' checks covered.

**This closes B0.3**: every one of the ~200 originally-estimated real
schedule points inside `engine.py` — precisely, all 56 entries in
`_TICK_JOBS`, the complete table — now runs through the B1/B2 runtime
instead of a direct per-tick method call. B0 (the prime invariant) is
correspondingly promoted from PARTIAL to fully SHIPPED.

Verified: `scripts/verify_b0_runtime_migrations.py` (175 checks) —
all pass, first run, no bug found. `verify_task_graph.py`/`verify_
scheduler.py`/`verify_runtime_invariant.py` re-run clean. A real
before/after `World.to_dict()` replay-hash check (`scripts/verify_
replay_hash.py --ticks 4000 --seeds 777 --in-process`) — MATCH,
byte-identical. `scripts/verify_native_soak.py` (3 seeds x 3000
ticks) — MATCH. `pyflakes` clean on both touched files (only the six
known pre-existing forward-ref findings in `engine.py`).

## [1.34.196] — Part B: B0.3 batch migration (ten more real jobs)

Explicit user instruction: "Don't ever do one at a time. Make this
your new principle, do as many as possible in one turn and ask
questions whenever stuck." New standing workflow rule recorded in
CLAUDE.md.

Migrated every remaining un-migrated `_TICK_JOBS` entry whose method
takes zero arguments (`_JOB_NO_ARGS`) onto the B1/B2 runtime in one
batch: `_maybe_spread_concepts`, `_maybe_spread_tradition_keeping`,
`_apply_trigger_rules_from_life_events`, `_maybe_tick_composite_
reactions`, `_maybe_schedule_record`, `_maybe_schedule_dispute`,
`_maybe_schedule_migration_decision`, `_schedule_due_cognition`,
`_schedule_due_dialogue`, `_schedule_voice_dialogue` — ten real jobs,
same shape as the first three migrations (own dedicated `TaskRegistry`/
`Scheduler` pair, CRITICAL+PERIODIC). `_JOB_EVENTS`/`_JOB_EVENTS_
SEASON` jobs (the majority of `_TICK_JOBS`) are explicitly out of
scope for this mechanism — they need `events`/`previous_season`
passed in fresh each tick, which `Task.fn`'s declared-once zero-arg
shape can't express without a real design change to `Task`/
`Scheduler` itself; flagged as real future work, not silently
dropped.

`scripts/verify_b0_runtime_migrations.py`'s `MIGRATIONS` table
extended to all 13 migrated jobs — the same generic 3-check-per-job
suite (declaration, job->scheduler resolution) plus the 6 shared
whole-batch checks (real invocation, clean-run report, 50-tick
persistence, exactly-once-per-tick, error capture, error propagation)
now covers 39 checks total.

Verified: `scripts/verify_b0_runtime_migrations.py` (39 checks) — all
pass, first run, no bug found. `verify_task_graph.py`/`verify_
scheduler.py`/`verify_runtime_invariant.py` re-run clean. A real
before/after `World.to_dict()` replay-hash check (`scripts/verify_
replay_hash.py --ticks 4000 --seeds 777 --in-process`) — MATCH,
byte-identical. `scripts/verify_native_soak.py` (3 seeds x 3000
ticks) — MATCH. `pyflakes` clean on both touched files (only the six
known pre-existing forward-ref findings in `engine.py`).

Scope: this migrates 13 of the ~200 real schedule points still living
directly inside `engine.py` — the `_JOB_EVENTS`/`_JOB_EVENTS_SEASON`
majority remain ordinary direct calls, blocked on a real `Task`/
`Scheduler` design extension to carry per-tick arguments, not on
willingness to migrate them.

## [1.34.195] — Part B: B0.3 third migration (`_maybe_tick_trigger_state_edges`)

Explicit user instruction: "Continue doing part B."

A third real `_TICK_JOBS` entry migrated onto the B1/B2 runtime,
following the exact per-job-dedicated-registry shape v1.34.193/.194
established: `SimulationEngine._maybe_tick_trigger_state_edges` (the
`on_drought`/`on_surplus` trigger-rule edge detector — small, self-
contained, already unconditional every tick, CRITICAL+PERIODIC so the
scheduler reproduces its "always runs" behavior exactly). Gets its own
`self._runtime_registry_trigger_edges`/`self._runtime_scheduler_
trigger_edges` pair, registered in `_RUNTIME_SCHEDULED_JOB_SCHEDULERS`
alongside naming and mind-authoring — avoiding the double-execution
bug class v1.34.194 caught and fixed, by construction, from the start.

`scripts/verify_b0_runtime_migrations.py` rewritten to be generic over
an arbitrary list of migrations (a `MIGRATIONS` table of `(method_name,
task_id, registry_attr, scheduler_attr)` tuples) rather than hardcoding
checks per job — now covers all three migrated jobs with one shared
check suite, including the load-bearing "each job's fn runs EXACTLY
ONCE per real `_tick_once()` call" no-double-execution proof. A future
fourth migration only needs one new tuple plus a registration check.

Verified: `scripts/verify_b0_runtime_migrations.py` (15 checks across
all three migrations) — all pass, first run, no bug found.
`verify_task_graph.py`/`verify_scheduler.py`/`verify_runtime_
invariant.py` re-run clean. A real before/after `World.to_dict()`
replay-hash check (`scripts/verify_replay_hash.py --ticks 4000 --seeds
777 --in-process`) — MATCH, byte-identical. `scripts/verify_native_
soak.py` (3 seeds x 3000 ticks) — MATCH. `pyflakes` clean on both
touched files (only the six known pre-existing forward-ref findings
in `engine.py`).

Scope unchanged from the prior two migrations' own framing: this is
the third of the ~200 real schedule points still living directly
inside `engine.py` — the other ~197 remain ordinary direct calls, same
"never big-bang, one subsystem at a time" discipline.

## [1.34.194] — Tier 0 rumor-first-listener lean + B0.3 second migration

Explicit user instruction: "Continue tier 0" / "Continue B" in one
message.

**Tier 0**: `Population.spread_rumor`'s FIRST listener (a caravan's/
letter's/deathbed-secret's real point of contact) was a genuine
uniform `rng.choice` with zero signal — the "real primary signal,
pillar lean only where there's no signal to override" shape used
across ~30 prior Tier 0 sites, just with the primary signal being
"none." New `RUMOR_FIRST_LISTENER_HUMANS_LEAN_MAX = 0.4`;
`spread_rumor` gained an optional `humans_lean` callable (`None`
reproduces the exact prior `rng.choice` byte-for-byte) weighing the
first draw toward whoever `humans_pillar` already has real standing
attention on. Threaded through all three real call sites: the caravan
rumor (engine.py), the letter rumor (engine.py), and the deathbed-
secret rumor (`_apply_inheritance`'s already-existing `humans_lean`
parameter, population.py). Verified via a 20,000-trial statistical
test (uniform baseline confirmed; a seeded lean toward one agent
measurably raised their draw rate ~3900->~5160 of 20000) and a
production-path smoke test through the real engine tick loop.

**Part B (B0.3)**: a second real job migrated onto the B1/B2 runtime,
following the same shape v1.34.193 established —
`SimulationEngine._maybe_retry_mind_authoring` (small, self-contained,
already unconditional every tick, CRITICAL+PERIODIC). A real design
bug was caught and fixed during implementation, not by the user:
sharing one `TaskRegistry`/`Scheduler` between two migrated jobs would
silently DOUBLE-EXECUTE both of them, since `_tick_once`'s loop calls
`run_tick()` once per migrated `_TICK_JOBS` slot and a shared
registry's `run_tick()` re-runs every task in it at each call. Fixed
by giving each migrated job its own dedicated registry+scheduler pair
(`self._runtime_registry_mind_authoring`/`self._runtime_scheduler_
mind_authoring`, alongside naming's existing pair) and a new
`_RUNTIME_SCHEDULED_JOB_SCHEDULERS` dict (method name -> scheduler
attribute name) replacing the old flat `_RUNTIME_SCHEDULED_JOB_NAMES`
set.

Verified: `scripts/verify_b0_runtime_migrations.py` (renamed/rewritten
from `verify_b0_naming_migration.py`, 10 checks) — both tasks
correctly declared in their own registries, `run_tick()` genuinely
invoking each bound method with real side effects, neither
skipped/deferred across 50 real ticks, and — the load-bearing check
for the per-job-registry fix — each migrated job's fn runs EXACTLY
ONCE per real `_tick_once()` call, not twice. A real before/after
`World.to_dict()` replay-hash check (4000 ticks, seed 777,
`--in-process`) — MATCH, byte-identical. `scripts/verify_native_
soak.py` (3 seeds x 3000 ticks) — MATCH. `scripts/verify_task_graph.py`/
`verify_scheduler.py`/`verify_runtime_invariant.py` re-run clean.
`pyflakes` clean on all touched/new files (only the six known
pre-existing forward-ref findings in `engine.py`).

## [1.34.193] — Tier 5 B0.3: first real subsystem migration onto the runtime

Explicit user instruction ("continue part B"). B10.2's kind-index
pilot pattern (`buildings_of_kind`/`vehicles_of_kind`/`institutions_
of_kind`) was confirmed genuinely exhausted this pass — every
remaining `scan_global_scans.py`-flagged site is either a full-grid
CA/terrain double loop, an unfiltered per-tick scan that must touch
every entity regardless of kind (no index would help), or a `.agents`
scan already covered by the `Population.get()` pilot. Scoped via
`AskUserQuestion` to "B0.3: a real subsystem migration onto the B1
task graph" — the first time B1's `TaskRegistry`/B2's `Scheduler`
(built and verified since v1.34.162/.164, never wired into `engine.py`)
execute a real schedule point instead of synthetic tasks in a verify
script.

`SimulationEngine._maybe_schedule_naming` migrated as the pilot: small,
self-contained, already unconditional every tick — declared `Priority
Class.CRITICAL` + `TriggerKind.PERIODIC` to reproduce that exact
"always runs" behavior through the scheduler rather than risk a real
change. `SimulationEngine.__init__` builds `self._runtime_registry`/
`self._runtime_scheduler`; `_tick_once`'s `_TICK_JOBS` loop keeps
naming in its exact ordering slot but routes it through `self.
_runtime_scheduler.run_tick()` via a new `_RUNTIME_SCHEDULED_JOB_
NAMES` frozenset. One real behavior-preservation risk found and
closed: `Scheduler._run_one` catches exceptions broadly (so one
budgeted task's failure can't take down a sibling's) where the
pre-migration direct call let an exception crash the tick outright —
`_tick_once`'s new call site re-raises a `RuntimeError` whenever
`report.errors` is non-empty.

Verified: a real before/after `World.to_dict()` replay-hash check
(4000 ticks, seed 777, `--in-process`) — MATCH, byte-identical; a
second multi-seed run (seeds 1/55/999, 3000 ticks) — also MATCH; new
`scripts/verify_b0_naming_migration.py` (10 checks, standalone) proving
the registry/task declaration, the real production early-out firing
correctly through the scheduler, `run_tick()` genuinely invoking the
bound method with real side effects on real engine state, the task
never skipped/deferred across 50 consecutive ticks, and an error inside
the migrated job propagating out of `_tick_once` instead of being
silently swallowed. Every pre-existing `scripts/verify_*.py` (native
soak included) re-run clean; `pyflakes` clean (only the six known
pre-existing forward-ref findings in `engine.py`).

Scope: migrates exactly ONE of the ~200 real schedule points — same
"never big-bang" discipline as every prior B-item. The other ~199
remain direct calls; a future migration can follow the same shape with
the plumbing risk already retired.

## [1.34.192] — Tier 5 B10.2 fourth pilot: institutions_of_kind index

Explicit user instruction ("continue part B"), scoped to a fourth
B10.2 site pilot — same shape as the three prior pilots.

New `Settlement.institutions_of_kind(kind)`: the institution-side
sibling of `buildings_of_kind()`/`vehicles_of_kind()`, replacing a
full `for inst in settlement.institutions: if inst.kind is not X:
continue` scan at six real call sites in `population.py`
(`_maybe_refresh_council`'s COUNCIL lookup, `_maybe_refresh_guild`'s
GUILD loop, `faction_of`, `council_faction_majority`'s COUNCIL
lookup, `family_of`, `fission_party`'s FAMILY loop).

`Institution.kind` never mutates in place anywhere in this codebase —
but unlike vehicles, institutions are appended at FIVE real call
sites (family/council/guild x2/faction founding) plus pruned at one
(the `INSTITUTION_LIST_MAX_STORED` filter-reassignment), so this
pilot's real risk was getting all SIX invalidation sites right rather
than just one.

Verified via a real before/after replay-hash check (MATCH, 4000
ticks, two independent process runs) and a new `scripts/verify_
institutions_by_kind_pilot.py` (16 checks, same negative-control
discipline as the prior pilots plus a real `faction_of`-shaped
consumer proof). Every one of the 19 pre-existing `verify_*.py`
scripts plus all three prior B10.2 pilot scripts re-run clean;
`pyflakes` clean. `scan_global_scans.py`'s flagged-site count fell
75 -> 72.

## [1.34.191] — Tier 5 B10.2 third pilot: vehicles_of_kind index

Explicit user instruction ("continue part B"), scoped via
`AskUserQuestion` to another B10.2 site pilot — same shape as the two
prior pilots (`Population.get`, `Settlement.buildings_of_kind`).

New `Settlement.vehicles_of_kind(kind)`: the vehicle-side sibling of
`buildings_of_kind()`, replacing a full per-tick/per-gather-event scan
of `settlement.vehicles` at seven real call sites (`_haul_factor`,
`_raft_factor`, `_agent_mount`, `_maybe_assign_mounts`, `_wear_carts`,
`_wear_rafts`, and `Settlement._vehicle_summary()` — itself called
from `Settlement.summary()`, whose per-tick cost is directly recorded
in a `simulation/engine.py` comment on a nearby call site: "summary()
... is expensive enough that calling it every tick for every
settlement measurably slowed the tick loop"). `summary()`'s own
building-kind filters (granaries/pastures/hatcheries/huts_standing/
the 13-kind `kind_counts` dict) were also converted to reuse
`buildings_of_kind()`, closing a gap the first buildings pilot hadn't
reached.

Simpler than the buildings-side index: `Vehicle.kind` never mutates in
place anywhere in this codebase and `Settlement.vehicles` is
append-only (no removal path exists), so `start_vehicle`'s own
explicit invalidation is the only real mutation site.

Verified via a real before/after replay-hash check (MATCH, 4000 ticks,
two independent process runs) and a new `scripts/verify_vehicles_by_
kind_pilot.py` (14 checks, including the same negative-control
discipline as the buildings pilot). Every one of the 19 pre-existing
`verify_*.py` scripts plus both prior B10.2 pilot scripts re-run
clean; `pyflakes` clean.

## [1.34.190] — Tier 5 B10.2 second pilot: buildings_of_kind index

Explicit user instruction ("start tier 5 part B left items"), scoped
via `AskUserQuestion` to "B10.2: one more site pilot" — a second,
bounded proof-of-pattern conversion, same shape as v1.34.184's
`Population.get(agent_id)` pilot.

New `Settlement.buildings_of_kind(kind)`: a `BuildingKind -> [Building]`
index, same derived/never-serialized/invalidate-on-mutation discipline
as the existing `_position_index` behind `at()`, replacing a full
per-tick scan of `settlement.buildings` at thirteen real call sites in
`population.py` (granaries, husbandry, workshops, tool/medicine
crafting, factories, docks, oil rigs, forges, market workers, schools,
the university upgrade, and the bridge-tile pooling scan). Unlike
`_position_index`, a building's `.kind` can change without the
buildings list changing length (the school->university upgrade), so
the new index is invalidated explicitly at all three real mutation
sites rather than relying on a length check.

Verified via a real before/after replay-hash check (MATCH across two
independent runs, 4000 ticks) and a new `scripts/verify_buildings_by_
kind_pilot.py` (29 checks, including a negative control proving the
cache can go stale without its real invalidation sites). `scripts/
scan_global_scans.py`'s flagged-site count fell 87 -> 76. Every prior
`verify_*.py` re-run clean; `pyflakes` clean. The remaining 76 flagged
sites, plus B0.3/B3.3/B4.2's other four candidates/B9.3, stay open.

## [1.34.189] — HCA amendment: competitive arbitration + cognitive domains

Explicit user directive ("one additional architecture pass before
implementation"), two amendments, docs-only, no code changed.

**Arbitration (§2.10, §3.3; roadmap Tier 7 B4-B7).** The first draft's
`w₁·surprise + w₂·urgency + w₃·staleness + w₄·goal_relevance` max was a
priority queue with a nicer name. Three defects, each fixed by a
distinct mechanism: a per-bid max cannot express *agreement* → bids
merge into coalitions before scoring (superadditive, sublinear,
independence-checked); fixed weights are not attention → historical
usefulness becomes a multiplicative *gain* on surprise/consequence, so
a proven bidder is amplified and a chronic false-alarmer attenuates
toward silence; exploitation-only scoring never investigates the
unknown → a `+β·√(uncertainty)` UCB term (Auer et al. 2002), the
principled **non-random** answer to exploration. Staleness becomes an
unbounded multiplier (competitive anti-starvation; B2.2's floor demoted
to a hard backstop). **No RNG anywhere in arbitration** — softmax
sampling explicitly rejected because it would break Mind-layer
replayability and make the Observatory's "why did this win?" panel
unanswerable. Specialists learn to bid from *measured* realised
outcomes, credited to winning and (where a counterfactual exists)
losing coalitions — L1 `learn()` applied to the bidding policy, hence
dependent on Stage G. Two non-negotiable guardrails: staleness gain is
never learnable (else starvation self-reinforces), and a bid is
credited only when its outcome was measured.

**Cognitive domains (§3.2; roadmap Tier 7 Stage H + E6).** Evaluated
whether the Adaptive Runtime and Player Model should be first-class
cognitive participants — finding: the Runtime **already is one in
substance** (B8 forecaster = `predict()`/`error()`, B5 `TaskMetrics` =
`observe()`, B15 `EscalationLadder` = an unarbitrated `bid()`, B13
`HypothesisLoop` = `learn()`), running unarbitrated and unobserved
while exercising real authority over how much the world gets to think.
Adds a `domain` type — `WORLD` / `MACHINE` / `OBSERVER` — on every
specialist, coalition and broadcast, with three load-bearing rules:
mechanically-enforced write scope (MACHINE writes only B6 tunables,
OBSERVER nothing; AST-checkable, extending
`verify_runtime_invariant.py`), no cross-domain budget competition (a
MACHINE bid sets the budget the WORLD domain arbitrates *within*, never
a rival inside it — the defence against the machine arguing the world
should think less and winning), and cross-domain flow only through L5
(so no settlement can form a belief about scheduling). The Player Model
joins as an OBSERVER specialist and is explicitly not the Town
Consciousness's interventions, which stay unchanged; Phase G's
discipline becomes partly structural.

Also: §0's "what actually changes" extended five items → seven; §4's
mapping table gained B6/B8.3/B13/B15.3 rows and re-scoped B2; §5 gained
two new predictions; §6.2's workspace panel gained per-factor breakdown
and a domain filter; §8 gained three new risks (machine starves mind,
learned gains collapse into self-reinforcing starvation, machine leaks
into fiction); §9 records that `HEARTHBENCH-RUNTIME-2026-07-23.md` is
textually unchanged but its *role* is amended — Part B is now itself a
mind, not only execution substrate, with B0's prime invariant
reinforced rather than weakened. `CLAUDE.md`'s standing HCA section
updated with both amendments.

Nothing implemented; same standing convention as the rest of HCA.

## [1.34.188] — HCA amendment: adaptive specialists (§2.5a)

Explicit user directive amending `docs/COGNITIVE-ARCHITECTURE-2026-08-
02.md`: "Every subsystem should itself be capable of adaptation.
Specialists should not remain static feature extractors forever. They
should accumulate experience, revise internal models, forget obsolete
assumptions, and improve predictions over time. The architecture
should evolve toward a society of learning cognitive processes rather
than a collection of fixed modules communicating through a
workspace." Docs-only, no code changed.

New §2.5a grounds the amendment in Complementary Learning Systems
theory (McClelland/McNaughton/O'Reilly 1995; Kumaran/Hassabis/
McClelland 2016) and adds a fifth L1 specialist method, `learn()`,
alongside `predict()`/`observe()`/`error()`/`bid()` — mapped directly
onto Tier 6's already-shipped L5 lifelong-learning primitives
(`ml/lifelong.py`: `ReplayBuffer`=interleaved replay, `continual_
train_mlp`=revise-not-replace, `passes_shadow_gate`=safe forgetting,
`CheckpointHistory`=bounded learning trail) plus L6's population-level
counterpart (`ml/evolution.py`, phylogeny vs. L5's ontogeny). New
Layer 4 paragraph distinguishes L4 chunking (discrete/symbolic,
impasse-gated) from L1 `learn()` (continuous/statistical, no impasse
needed) — the two compose, neither requires the other. `learn()`
always runs async/offline per B0's prime invariant, never live-tick
gradient descent, never raises bid frequency.

Roadmap: new Tier 7 Stage G ("Learning specialists," G1-G4) inserted
between Stage D (Memory) and Stage E (Observatory) in both the HCA
doc's §7 and `docs/ROADMAP-2026-07-REMAINING.md`'s checklist — G1 (the
`learn()` interface wired to L5), G2 (the first concrete target: B8's
`WorkloadForecaster`, with a falsifiable forecast-error-improvement
test and a shadow-gate-rejects-worse-retrain test), G3 (forget
obsolete assumptions, via a synthetic regime-change test), G4 (L6
population variation for one specialist family). New Stage E item E5
(a future per-specialist learning-curves Observatory panel, gated on
Stage G). New §8 risk ("a learning specialist can catastrophically
forget or drift silently worse — the shadow gate is only as good as
its held-out metric"). §0's "what actually changes" list extended
four items -> five. §4's Tier-6-to-HCA mapping table gained two new
rows (L5 -> `learn()`, L6 -> specialist-level variation/selection).
This file's own standing "## The Cognitive Architecture — HCA" section
updated to match (L1 bullet + a new dedicated paragraph).

Same standing convention as the rest of HCA: nothing implemented yet;
work from Stage G only on future explicit direction naming a specific
item (G1-G4).

## [1.34.187] — Tier 5 B4.2 pilot: "idle institutions" dormancy

Explicit user instruction ("continue part B of tier 5"), resolved via
`AskUserQuestion` into "B4.2 pilot: one dormancy candidate," then a
second `AskUserQuestion` choosing "idle institutions" among B4.2's five
named candidates — the only one compliant with B15's `TWO_PART_
GUARANTEE` without a real lossless elapsed-tick reconstruction, since
it gates Mind-layer LLM scheduling attention rather than any Body-
deterministic per-tick simulation.

New `SimulationEngine._update_institution_dormancy` (monthly): tracks
each real `(settlement, institution)` pair's cheap fingerprint and
sleeps/wakes it via the existing `DormancyManager` (B4.1/B4.3/B4.4,
v1.34.166). `_institution_job_target`'s quarterly round-robin now
excludes sleeping institutions, concentrating the `institution_culture`
LLM call on institutions something has actually happened to.

Verified: direct production-path tests against a real
`SimulationEngine` covering registration, sleep-after-threshold,
wake-on-change, non-`month_end` no-op, the all-dormant fallback, and a
two-institution round-robin selecting only the active one; the full
`scripts/verify_*.py` sweep; a 4000-tick LLM-disabled soak with a
clean round-trip (dormancy state correctly never touches persisted
World/Settlement state).

## [1.34.186] — Tier 7 preflight P1/P2: two real bug fixes

Explicit user instruction: fix the two bugs found in the prior
diagnostic pass, then continue Tier 5 Part B.

**P1**: new `LARGE_SCHEMA_REASONING_NUM_PREDICT_MULT = 1.75`
(`simulation/engine.py`) generalises `PERSONAL_BELIEF_NUM_PREDICT_
MULT`'s v1.6.0 fix — extra token headroom for a `deep_reasoning=True`
job whose large output schema can exhaust the shared flat budget before
JSON is ever written — to `ontology_proposal`, `beliefs`,
`institution_belief`, and `narrative_direction`. The soak's own
`ontology_proposal` call had returned `raw_model_output: ""`.

**P2**: `llm/laws.py`'s `SYSTEM_PROMPT` rewritten. It previously told
the model "Most of the time it is NOT yet settled, and that is the
correct answer" unconditionally — biasing toward `forms: false`
regardless of how many times the hardship had recurred. The soak's own
prompt cited 590 occurrences and still refused to form a rule. Now
explicit that a handful of occurrences is still "too soon" (unchanged
epistemic humility) but dozens-to-hundreds with no rule in place is
itself evidence worth weighing honestly.

Verified: a direct end-to-end test with a fake `CognitionRunner.client`
confirming the real request `num_predict` scales correctly for all
four P1 call sites, and that an unrelated reasoning job with no
override is unaffected; a direct check of the new prompt wording; the
full existing `scripts/verify_*.py` sweep (20 scripts) re-run clean;
a 4000-tick LLM-disabled soak with a clean round-trip.

## [1.34.185] — The Hearthmind Cognitive Architecture (HCA), docs-only

Explicit user directive reframing the project's own primary goal:
Hearthmind exists to explore whether human-like cognition can emerge
from interacting computational systems; NPCs are a consequence of that
goal, not the goal itself; functionally mimic how a brain is
*organised* (many specialised subconscious systems, little reaching
conscious reasoning); **treat the LLM as one cognitive subsystem, not
the mind**; apply the same principle at every scale; and build a
runtime UI that is a *cognitive observatory*. The directive explicitly
asked for documentation and justification **before** implementation —
so this release changes no code.

**New: `docs/COGNITIVE-ARCHITECTURE-2026-08-02.md`.** Authoritative for
how minds are organised at every scale. Six scale-generic layers (L0
substrate → L1 specialists that *bid* rather than call → L2
activation-ranked working memory → L3 global workspace with one
arbitrated winner **broadcast to all**, resolved by chunk/model/LLM →
L4 impasse-gated deliberation + chunking → L5 metacognition + attention
schema), nested so one mind's broadcast is a larger mind's input.

**Grounded in the user's own 64,453-tick soak, not theory alone.** Four
measured pathologies, each targeted by one adopted principle: ~93% of
LLM calls went to ambient narration while pillar-level cognition got
~37 calls total; `reflection_notebook_total: 0` (the metacognitive
layer was "Eligible / Deferred" and never ran once); 93% of the
emergence log is `unexplained_shift`, nearly all of it "content agent
decided to socialize"; and 590 identical hardships produced 7
deliberations and 0 rules with no memory that the question was already
asked.

**Principles adopted** (each with what was *left*): Standard Model of
Mind (Laird/Lebiere/Rosenbloom 2017) as structural anchor; Global
Workspace Theory (competition + broadcast); predictive processing
(precision-weighted surprise as salience); Soar (typed impasses +
chunking); ACT-R (base-level activation, replacing four hand-tuned
retrieval mechanisms); Attention Schema Theory; Clarion/dual-process.
**Explicitly rejected:** spiking-neural substrate, full Bayesian active
inference, monolithic "agent brain" prompts, and any claim that this
architecture produces sentience — it is a bet on *functional*
organisation, and the code must stay honest about that difference.

**Roadmap: new Tier 7**, 17 items across preflight/surprise/workspace/
impasse/memory/observatory/semantic-pointers. **Every item carries a
falsifiable success test** — the structural guard against renaming
existing systems in cognitive-architecture vocabulary and calling it
progress. Tiers 5 and 6 are **re-scoped as HCA's substrate, not
discarded**, which is also the honest explanation for why both have
felt inert: Tier 5 built a runtime with no client and Tier 6 built
resolvers with nothing to resolve; Tier 7 is the consumer. Mapping is
close to one-to-one.

**UI: the two-surface rule is amended to three** — The World (map,
*what is happening*), The Mind (Cognitive Observatory, *how is it being
thought about*), The Machine (`⚙ dev`, *is the runtime healthy*). A
promotion, not a leak: watching cognition is the stated point of the
project. **Phase G is unaffected and explicitly re-scoped** — the Town
Consciousness's own workspace stays dev-console-only exactly as today,
and the Observatory never narrates anything as supernatural.

**Headline falsification test:** deliberative cost per unit of
emergence must FALL as a world matures. If LLM calls fall but emergence
falls proportionally, impasse-gating is just starvation with extra
steps and this direction should be abandoned.

Two incidental bugs found in the same diagnostic and filed as Tier 7
preflight (not architecture): `ontology_proposal` returns
`raw_model_output: ""` — the v1.6.0 `PERSONAL_BELIEF_NUM_PREDICT_MULT`
fix was never generalised to the other large-schema reasoning jobs; and
the `laws` prompt is biased toward "not yet" (7 calls, 0 rules).

Also updated: `CLAUDE.md` (new standing HCA section, three-surface UI
amendment, current-state entry), `docs/ROADMAP-2026-07-REMAINING.md`
(Tier 7), `docs/README.md` (index entry).

## [1.34.127] — Tier 0's thirty-fourth conversion: a new occupation-shortage Village producer

Explicit user decision via `AskUserQuestion` (following a codebase-wide
re-scan that found no more sites with the established real-signal-plus-
arbitrary-tiebreak shape and existing pillar content to lean on):
"Design a new producer." Village pillar's fourth category-keyed
`world_model` subject (after dispute_feud/theft/materials_bottleneck),
this one keyed by a literal `occupations.py` occupation string.

New `SimulationEngine._detect_occupation_shortage` (riding the existing
daily-metrics cadence, edge-triggered like `_detect_settlement_
bottlenecks`): a settlement whose living population is at or above
`OCCUPATION_SHORTAGE_POPULATION_THRESHOLD` (15) with zero living
holders of some occupation (MAYOR excluded — its cap of one holder
makes "zero" a normal steady state, not a shortage) mirrors/revises a
`village_pillar.world_model` entry keyed by that occupation's name.

Real consumer: `_maybe_assign_occupations`'s least-represented-
occupation pick (`min(candidates, key=counts[o])`) gains `Population.
OCCUPATION_PILLAR_LEAN_MAX = 0.5` as a second tuple key — an occupation
the village already has a standing "we could use one" theory about is
picked FIRST among occupations tied at the same count (the common
early-game case, several occupations at zero). Real counts always
dominate (tuple comparison checks `counts[o]` first); the lean only
ever resolves a genuine tie. Wired via the same "compute once per tick
over a small fixed set" pattern `building_kind_pillar_lean` already
established, new `occupation_pillar_lean` dict computed once in
`World.tick()` over `ALL_OCCUPATIONS` (~13 entries).

Verified: a direct production-path test of the producer (forms,
revises in place, stays silent on repeat firings, clears on recovery),
a direct production-path test of the consumer through the real
`_maybe_assign_occupations` (no-lean picks the first tied occupation,
a seeded lean flips the pick), a 4000-tick LLM-disabled soak with
clean round-trip, `pyflakes` clean. No native module touched. Tier 0
now has thirty-four real converted sites.

## [1.34.126] — Tier 0's thirty-second/thirty-third conversions: core-cast rotation + district collectivization

Explicit user instruction: "Convert as many sites of tier 0 as you can
in this turn." Two more sites, both the same `(real signal, -id)`
arbitrary-tiebreak shape as the two prior sessions' sites.

**Thirty-second**: `_maybe_rotate_core_cast`'s outgoing (`min`)/
incoming (`max`) picks were both `(prominence, -id)` — real signal,
but an arbitrary highest-id tiebreak whenever two candidates land on
the exact same prominence (common at the extremes: several freshly-
arrived core members near-zero prominence, or several outsiders with
no bond/skill/reputation event yet). New `Population.CORE_CAST_
ROTATION_HUMANS_LEAN_MAX=0.15` folds `humans_pillar.subject_
confidence(agent.name)` in as a shared-sign middle key: under `min`
(outgoing) a higher lean makes a tied candidate LESS likely to be
picked (protects them from demotion); under `max` (incoming) a higher
lean makes a tied candidate MORE likely to be picked (favors them for
promotion) — the same real regard, read two different ways depending
on which side of the swap it's weighing. Wired directly at the engine.
py call site (a monthly job, not a per-tick path) via a lazy lambda.

**Thirty-third**: `_maybe_collectivize_excess_population`'s (D6)
candidate-for-removal sort was pure `_prominence` ascending — real
signal, but every tied-at-zero agent (common: new/unremarkable
non-core people) was ordered arbitrarily by iteration order. Same
`humans_lean` treatment, new `Population.DISTRICT_HUMANS_LEAN_MAX=
0.15` — a higher lean sorts an agent LATER (protects them from being
folded into a district). `humans_lean=None` reproduces the exact
prior ordering on both sites, verified directly (Python's tuple-key
comparison never lets the lean term override a real prominence
difference — it only ever resolves genuine ties).

Verified: direct tuple-key tests for both sites (tie-break flip, real
signal never overridden), production-path tests through the real
`_maybe_rotate_core_cast` (a forced tied-prominence scenario flips
both outgoing and incoming) and `_maybe_collectivize_excess_
population` (a small monkeypatched `DISTRICT_INDIVIDUAL_CAP`, three
tied agents, a seeded lean shifts which one gets collectivized), a
4000-tick LLM-disabled soak with clean round-trip, `pyflakes` clean.
No native module touched. Tier 0 now has thirty-three real converted
sites.

## [1.34.125] — Tier 0's thirty-first conversion: inheritance heir pick gains a pillar lean

Explicit user instruction: "Continue tier 0." `Population._apply_
inheritance`'s heir pick was `max(candidates, key=(bond, -id))` — a
real relationship-strength signal, but its `-id` tiebreak fires
whenever two family candidates have EXACTLY equal bond, the common
case for relatives who never actually interacted with the deceased
(both default to 0.0). New `Population.HEIR_HUMANS_LEAN_MAX = 0.15`
folds `humans_pillar.subject_confidence(agent.name)` in as a second
key, ahead of `-id` but behind the real bond value (max's tuple
comparison is lexicographic, so a genuine bond difference can never
be overridden) — only the arbitrary highest-id fallback is replaced
with something meaningful.

No new wiring needed: `_apply_deaths`/`_apply_inheritance` gained the
same `humans_lean: Callable[[Agent], float] | None` param already
threaded through `Population.tick()` for the HUT-owner site
(v1.34.124) — `World.tick()`'s existing lazy lambda reaches this site
for free.

Verified: a direct tuple-key test (no-lean ties toward lowest id, a
seeded lean flips the tie, a genuine bond difference is never
overridden by the lean), a production-path test through the real
`_apply_inheritance` (a HUT's `owner_agent_id` transfers to the
lowest-id tied candidate with no lean, to the leaned candidate with
one), a 4000-tick LLM-disabled soak with clean round-trip, `pyflakes`
clean. No native module touched. Tier 0 now has thirty-one real
converted sites.

## [1.34.124] — Tier 0's thirtieth conversion: HUT-owner pick gains a pillar lean

Explicit user instruction: "Continue tier 0." `Population._maybe_start_
construction`'s HUT-owner pick was already ambition-weighted
(`TRAIT_AMBITION_FOUNDER_SELECTION_WEIGHT`) — the same shape as
`deliberate_guild_candidate`'s founder pick and `fission_candidate`'s
leader pick, both already converted. New `Population.HUT_OWNER_HUMANS_
LEAN_MAX = 0.2` (half the trait's own weight, same scale `GUILD_
FOUNDER_HUMANS_LEAN_MAX` uses for the analogous guild-founder site)
adds `humans_pillar.subject_confidence(agent.name)` as a second,
smaller term — real ambition stays dominant.

`Population` is deliberately decoupled from pillar state, and this
site fires every tick for every colocated founder group (rare to
actually reach the HUT branch, but the surrounding scan runs
constantly) — so the pillar lookup is threaded as a LAZY callable
(`humans_lean: Callable[[Agent], float] | None`), same technique
`due_for_dispute` established (v1.34.114): `World.tick()` passes
`lambda a: self.humans_pillar.subject_confidence(a.name)` through
`Population.tick()` -> `_maybe_start_construction`, only ever invoked
against the small `eligible` founder list actually being weighed, not
the whole population.

Verified: a direct weight-formula test (no-lean favors ambition,
lean raises the leaned agent's weight), a 400-trial production-path
statistical test through the real `_maybe_start_construction` (no-lean:
high-ambition agent wins ownership 240/400; a seeded lean toward the
low-ambition agent raises their win rate from 179/400 baseline to
202/400), a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean. No native module touched. Tier 0 now has thirty real
converted sites.

## [1.34.123] — Live-diagnostic pass: unreachable wildfire threshold fixed + backpressure/reasoning-timeout diagnostics

Explicit user request: a pasted live "long live run diagnostics" report
(42,013 ticks) with "expose more diagnostics if you think it would
help debugging things deeper and also fix issues from this report."

**Real bug fixed**: `wildfire_ignition_ticks_recorded: 0` over the
whole 42,013-tick run — the exact "unreachable threshold" bug class
CLAUDE.md documents for flood/snow/wind (v0.88.0/v1.34.64). `world/
disasters.py`'s `tick_wildfire` only rolls its 1.5%/week ignition
chance when `weather.precipitation < WILDFIRE_DRY_PRECIPITATION`
(0.1) on a summer week boundary — but `compute_weather`'s EMA
smoothing never actually produces that low a summer reading. Measured
directly (10 seeds x 4 years, driven with a real `SimClock`, same
technique CLAUDE.md's own weather lesson prescribes): summer
week-boundary precipitation's realized minimum is ~0.145, its 5th
percentile ~0.217 — 0.1 sat below the floor of what's reachable,
making wildfires structurally impossible regardless of chance/
temperament/heatwave tuning. Raised `WILDFIRE_DRY_PRECIPITATION` to
0.25 (this measurement's own ~19th percentile — a real "drier than
typical" gate, not the unreachable one). Verified: a direct 20-seed
x 20-year `tick_wildfire` production-path run over solid forest
terrain produced 20 real ignitions against 15 expected from the
measured qualifying-week count x the unchanged 1.5% weekly roll —
confirming the fix is reachable at roughly the intended rate, not
just "no longer literally zero."

**New diagnostics, both grounded in specific fields the pasted report
made hard to interpret by hand**:

1. `CognitionRunner.reasoning_calls_near_timeout` (`llm/jobs.py`) — the
   report's reasoning latency percentiles (p50 87.9s/p95 171.1s/max
   192.2s) sat right against this deployment's own scaled timeout
   ceilings, but `latency_ms_p50/p95/max` only ever reflect calls that
   SUCCEEDED — a deployment where most reasoning calls are timing out
   would show the same "healthy-looking" percentiles from just the few
   that happened to finish, with the timed-out majority invisible
   except as a separately-read `calls_timed_out` count. A succeeded
   reasoning call within `NEAR_TIMEOUT_FRACTION` (0.85) of the exact
   ceiling `_run_gated` used for that specific call now increments this
   counter — a leading indicator visible before the first real timeout.
   Surfaced as `llm_stats.reasoning.calls_near_timeout`.
2. `SimulationEngine._backpressure_pressure_band()` — the report showed
   `llm_backpressure_limit_effective: 1` (== `llm_max_concurrent`, the
   adaptive floor) alongside `calls_dropped_backpressure` far exceeding
   `calls_attempted`; confirming that was `_current_backpressure_
   limit()` correctly tightening under severe measured p95 latency
   (not a scheduling bug) required manually cross-referencing `latency_
   ms_p95` against `ADAPTIVE_LATENCY_SEVERE_MS`. Now surfaced directly
   as `llm_backpressure_pressure_band` ("healthy"/"elevated"/"severe")
   in `/diagnostics`.

**Investigated, not changed** (both explicitly NOT guessed at, per this
project's own standing "don't silently re-tune without a live A/B"
discipline for `llm_max_concurrent`): the backpressure-drop volume
itself is `_current_backpressure_limit()` working as designed once
`llm_max_concurrent=1` (its own floor) can't be tightened further under
sustained severe latency — a hardware/model-size lever, not a code bug,
and `llm_max_concurrent` has flip-flopped many times in this project's
history based on exactly this kind of live measurement; changing it
again needs the user's own call, not a guess from one report. The empty
`reflection_notebook` alongside a populated `reflection_pillar.
world_model` matches v1.23.1's already-documented Reflection cold-start
latency (first real output needs ~70k ticks) — not a bug, the report's
own 42,013 ticks simply hasn't reached it yet.

Verified: direct unit tests for both new diagnostics (near-timeout
counter via a fake slow/fast adapter; pressure band via a real engine
with synthetic forced latency), a direct 20-seed x 20-year `tick_
wildfire` production-path test confirming the fix's reachability and
rate, `pyflakes` clean, a 4000-tick LLM-disabled soak with a clean
round-trip. No native module touched (pure Python throughout).

## [1.34.122] — Tier 0's twenty-ninth conversion: choose_building_kind gains a pillar lean

Explicit user decision via `AskUserQuestion`: "Reopen choose_building_
kind" — the one remaining big Tier 0-adjacent lever, a deliberately
reopened, already live-diagnostic-tuned system (`PRIORITY_KIND_
BOOST=2.5`, `ERA_BRANCH_BOOST=1.35`). New `pillar_lean: dict[str,
float] | None` param on `buildings.choose_building_kind`, applied
AFTER both existing multiplicative boosts via a new, deliberately
smaller `BUILDING_KIND_PILLAR_LEAN_MAX=1.15` — "the village keeps
building what it tends to build," real cultural momentum, subordinate
to both town_brain's real decided priority and era_branch's LLM-
authored character. `pillar_lean=None` (the default) reproduces the
exact prior weights and RNG-consumption pattern byte-for-byte —
verified directly, not just asserted.

New producer: `Population._maybe_start_construction`'s real "{Kind}
construction began/was staked out..." life event (category `"
construction_started"`) is the one place engine.py can recover WHICH
kind was actually chosen without threading a new structured field
through `World.last_life_events` — `_tick_once`'s per-tick loop
parses the kind off that description's own stable shared template and
mirrors `village_pillar.world_model` keyed by the literal kind value,
revised in place, same shape as every other category-keyed producer
this session. `World.tick()` computes the full `building_kind_pillar_
lean` dict ONCE per tick (a cheap bounded scan over a fixed dozen-ish
kinds, not per-candidate-site or per-agent) since `Population`
deliberately doesn't reference pillar state, threaded through `Population.
tick` -> `_maybe_start_construction` -> `choose_building_kind`.

Verified: a direct RNG-parity test (`pillar_lean=None` reproduces the
exact prior pick), a direct statistical test (a leaned kind's share
rises measurably, 3000 trials), a production-path statistical test
through the real `Population._maybe_start_construction` on real
world terrain (a leaned eligible kind's real construction share rises
measurably, 400 trials), a production-path test through the real
`_tick_once` (the construction mirror forms and revises in place), a
real `World.tick()` call with a seeded pillar lean present confirming
no crash, a 4000-tick LLM-disabled soak with clean round-trip,
`pyflakes` clean across all four touched files. No native module
touched (pure Python throughout). Tier 0 now has twenty-nine real
converted sites.

## [1.34.121] — Tier 0's twenty-eighth conversion: deliberate guild founding's skill pick

Explicit user instruction: "Convert more sites and ask if you get
stuck," continuing after v1.34.120's producer. Found by re-auditing
`Population.deliberate_guild_candidate`: a fixed `(farming,
construction, medicine)` tuple order meant whichever skill happened
to come first in that order won outright whenever two skills
qualified for deliberate founding the same month — a structural bias,
not a meaningful choice.

No new producer needed this time — `_maybe_schedule_guild_founding`'s
own apply() has mirrored `village_pillar.world_model` with subject
`"the {skill} guild"` since v0.64.0-era work; `subject_confidence`'s
substring match already catches a bare skill name (`"farming"`)
against that existing subject (`"the farming guild"`). Rewrote
`deliberate_guild_candidate` to collect every qualifying skill first,
then pick via a new `skill_lean: dict[str, float] | None` param
(`skill_lean.get(skill, 0.0)`, computed by the caller from `village_
pillar.subject_confidence(skill)` over the three real skill names) —
first-max-wins reproduces the exact prior fixed-order pick when no
lean exists anywhere.

Verified: a direct test (two simultaneously-qualifying skills,
no-lean picks farming first as before, a seeded lean flips the pick
to construction), a production-path test through the real `_maybe_
schedule_guild_founding` (no-lean prompt names farming; a real prior
`"the construction guild"` mirror entry flips the prompt to name
construction instead), a 4000-tick LLM-disabled soak with clean
round-trip, `pyflakes` clean. Tier 0 now has twenty-eight real
converted sites.

## [1.34.120] — Tier 0's twenty-seventh conversion: Village's third category subject (materials_bottleneck)

Explicit user decision via `AskUserQuestion`: "Another new producer."
Extends v1.34.118's Village category-keyed producer with a third
subject — `_detect_settlement_bottlenecks`'s existing edge-trigger
(a settlement genuinely crossing INTO a materials shortage) now also
mirrors `village_pillar.world_model` keyed by the literal word
`"materials_bottleneck"`, revised in place, same shape as the
dispute_feud/theft mirrors.

Unlike those two (added purely as a tiebreak input), this is a genuine
THIRD *candidate* in `_maybe_schedule_laws`'s `candidates` dict — its
own real occurrence count can now win the `pattern_key` pick outright
and produce an actual law about the shortage, not just break a tie.
New `_LAW_PATTERN_TEXT["materials_bottleneck"]` label. Real bug caught
and fixed while wiring the third candidate: the post-formation reset
(`if pattern_key == "theft": reset theft; else: reset dispute_feud`)
was hardcoded for exactly two non-theft candidates — with a third
candidate this would have reset the WRONG signal whenever materials_
bottleneck won, leaving it un-reset (immediate re-fire risk) while
incorrectly zeroing an untouched dispute_feud count. Generalized to
`stl.pattern_signal_counts[pattern_key] = 0` for any non-theft winner.

Verified: a production-path test through the real `_detect_settlement_
bottlenecks` (forced materials shortage, confirms the mirror forms),
a production-path test through the real `_maybe_schedule_laws` (
materials_bottleneck as the sole eligible candidate wins outright, the
prompt names it, a real `forms: true` apply() resets only its own
counter), a regression test confirming theft-wins still resets
correctly and leaves the other two counters untouched, a 4000-tick
LLM-disabled soak with clean round-trip, `pyflakes` clean. Tier 0 now
has twenty-seven real converted sites.

## [1.34.119] — Tier 0's twenty-sixth conversion: composite-reaction feuding-pair pick

Explicit user instruction: "Convert more sites and ask if you get
stuck." Found by re-auditing `_maybe_tick_composite_reactions` (per-
tick job, unlike most Tier 0 sites) for a WHICH-candidate pick: when
more than one settlement-wide feuding FAMILY pair exists (rare, but
possible), `feuding_pair = next(...)` picked the first one found in
nested iteration order — the pair a matching `relationship_rupture`
composite reaction (e.g. "Desperate Times") actually escalates.

Rewritten to collect every feuding pair first (same O(families²) cost
the original generator already paid every tick — no new complexity in
the common 0-or-1-pair case), then, only when 2+ pairs exist, pick via
`village_pillar.subject_confidence` summed over both family names —
the pillar lookup is bounded to this already-small candidate set and
never runs at all on the common single-or-zero-pair tick. No real
priority signal exists here (unlike faction/rule_propose's magnitude-
based picks) — this is a genuine first-max-wins uniform pick, the same
shape as several earlier Humans-lean sites (inventor selection,
dream, migration_decision).

Verified: a production-path test through the real `_maybe_tick_
composite_reactions` (two synthetic feuding family pairs, a forced
matching reaction, real `_apply_composite_reaction` call — no-lean
picks the first-found pair, a seeded `village_pillar` belief on the
second pair's family names flips the pick), a 4000-tick LLM-disabled
soak with clean round-trip, `pyflakes` clean. Tier 0 now has
twenty-six real converted sites.

## [1.34.118] — Tier 0's twenty-fifth conversion: Village's category-keyed producer + laws tiebreak

Explicit user instruction: "Yes new producer" (following a report that
a broad sweep had found no further genuinely-reachable tiebreak
site). Village pillar's `world_model` has so far only ever been keyed
by settlement/institution/agent names — never by an abstract signal
category, the same gap Nature had before v1.34.106/107's species-keyed
producer. This ships Village's own version of that shape.

Two new producer touch points, both revise-in-place via `find_world_
model_entry` (same discipline as every prior category-keyed producer):
(1) `_maybe_schedule_dispute`'s real `apply()`, on a genuine `outcome
== "feud"` — mirrors `village_pillar.world_model` keyed by the literal
word `"dispute_feud"`, alongside the existing `pattern_signal_counts`
increment. (2) `_tick_once`'s per-tick `last_life_events` loop (the one
place engine.py sees a theft occur — `Population.law_signal_counts
["theft"]`'s own increment lives in `population.py`, decoupled from
pillar access by design) — mirrors keyed by `"theft"` whenever the tick
carries at least one theft entry.

Real consumer: `_maybe_schedule_laws`'s `pattern_key = max(candidates,
key=candidates.get)` picked between `{"theft": count, "dispute_feud":
count}` with no tiebreak — `max`'s key gained `village_pillar.subject_
confidence(k)` as a second, tie-break-only element. Real occurrence
count stays the sole determinant except in a genuine tie.

Verified: a direct test of the generic revise-in-place mechanics, a
production-path test through the real `_tick_once` (a synthetic theft
`last_life_events` entry forms then revises the `"theft"` mirror
in-place across two real ticks), a production-path test through the
real `_maybe_schedule_dispute`'s `apply()` (a forced `feud` outcome
forms the `"dispute_feud"` mirror), a production-path test through the
real `_maybe_schedule_laws` (a genuine count tie between theft and
dispute_feud, no-lean picks theft, a seeded `village_pillar` belief
flips the pick to dispute_feud), a 4000-tick LLM-disabled soak with
clean round-trip, `pyflakes` clean. Tier 0 now has twenty-five real
converted sites, and Village pillar has its first category-keyed
producer (joining Humans' agent-keyed and Nature's species-keyed
producers).

## [1.34.117] — Tier 0's twenty-fourth conversion: false_memory contagion partner tiebreak

Explicit user instruction: "Keep converting as many sites as you can,
if ever stuck ask." A broad re-sweep across `simulation/engine.py`,
`agents/population.py`, and the `world`/`settlement`/`llm` modules
found no further site with a genuinely reachable tie except one
Phase-G-adjacent candidate, flagged via `AskUserQuestion` rather than
guessed: `_apply_consciousness_intervention`'s `false_memory` branch
picks the recipient's strongest-bonded partner for emotional
contagion — `partner_id = max(primary.relationships, key=lambda aid:
primary.relationships[aid])`. Unlike the faction/omen/observer sites,
relationship strength is a continuously-nudged float, so an exact tie
is rare — flagged honestly as likely-permanent-no-op rather than
converted silently. Explicit user decision: convert anyway, for
consistency with the other Phase G carve-out sites.

`max`'s key gained a second, tie-break-only element: `humans_pillar.
subject_confidence(partner.name)`. Real bond strength stays the sole
determinant; the lean only matters in the rare case of an exact float
tie.

Verified: a direct test (no-lean picks the first-max bond, a seeded
tie is broken toward the leaned partner, real bond strength is never
overridden), a production-path test through the real `_apply_
consciousness_intervention("false_memory", ...)` (a genuine tie seeded
between two bonds, confirming the leaned partner — not the other —
receives the planted memory), a 4000-tick LLM-disabled soak with
clean round-trip, `pyflakes` clean. Tier 0 now has twenty-four real
converted sites.

## [1.34.116] — Tier 0's twenty-second/twenty-third conversions: faction cluster + consciousness target tiebreaks

Explicit user decision via `AskUserQuestion` on the two sites flagged
as needing a call: both approved.

**Faction cluster pick (twenty-second site).** `Population._detect_
faction_candidate`'s cluster selection already had a real primary
signal (cohesion) plus a real tiebreak (cluster size) — the safest
Tier 0 shape. A genuine tie between two equally-cohesive, equally-sized
clusters (rare, but possible) previously fell to Python dict/union-find
iteration order. New optional `humans_lean: dict[int, float] | None`
param; `max`'s key is now `(cohesion(c), len(c), cluster_lean(c))`
where `cluster_lean` averages `humans_pillar.subject_confidence` over
the cluster's own members. `_maybe_schedule_faction` (`simulation/
engine.py`) computes the lean dict from settlement members before
calling detection. Real cohesion/size signals stay the sole
determinant except in a genuine tie.

**Consciousness target pick (twenty-third site).** Explicit user
decision extending v1.34.9/v1.34.114's Phase G carve-out (previously
scoped to omen's own subject pick) to `_observer_favorite_agent`'s
tie-break — this helper selects WHO a monthly consciousness
intervention (false memory, omen subject, misplaced object) targets
among core-cast agents tied for most player-viewed. The `sorted(...)`
key gained a second element, `humans_pillar.subject_confidence(agent.
name)`, both descending — real view count stays the sole determinant
except in a genuine tie, at which point the tied agent Humans already
has a standing theory about wins. Never changes WHETHER an
intervention happens or its content, only which equally-viewed core-
cast agent it targets.

Verified: a direct test of `_detect_faction_candidate` (no-lean picks
whichever cluster union-find finds first, a seeded lean flips a
genuine tie, a large lean on a strictly smaller cluster can never
override real cluster size), a direct test of `_observer_favorite_
agent` (tie broken toward the leaned agent, a strictly higher real
view count is never overridden by lean), a production-path test
through the real `_maybe_schedule_faction` (two disjoint same-size
same-cohesion clusters, a seeded `humans_pillar` belief flips which
cluster gets named), a 4000-tick LLM-disabled soak with clean
round-trip, `pyflakes` clean. Tier 0 now has twenty-three real
converted sites.

## [1.34.115] — Tier 0's twenty-first conversion: rule_propose's stuck-institution tiebreak

Explicit user instruction: "Convert as many sites as you can." Found
by re-auditing `_maybe_schedule_rule_proposal` (`simulation/engine.py`)
for the "real primary signal + pure tiebreak" shape the first two Tier
0 sites (`town_brain.compute_priority`, `era_branch.compute_branch`)
established — the safest category, since a lean can only ever break a
genuine tie in real state, never override it.

`stuck_institution = max(..., key=lambda i: i.objective_ticks_unmet, default=None)`
picked whichever institution has gone longest without its objective
being met, but never once used any second key when two institutions
were equally stuck — Python's plain iteration order silently decided.
The `max` key is now `(i.objective_ticks_unmet, village_pillar.
subject_confidence(i.name))`: `objective_ticks_unmet` stays the sole
determinant except in a genuine tie, at which point the institution
`village_pillar` already has a standing theory about wins. No lean
anywhere reproduces the exact prior first-found tie-break (Python's
`max` picks the first max encountered).

Verified: a direct logic test (tie broken toward the leaned
institution, no-lean reproduces first-found, a large lean on a
LOWER-`objective_ticks_unmet` institution can never win — the real
signal is never overridden), a production-path test through the real
`_maybe_schedule_rule_proposal` (a seeded `village_pillar` belief about
one of two equally-stuck institutions flips which one grounds the
prompt; a fresh no-lean call reproduces the original first-found
pick), a 4000-tick LLM-disabled soak with clean round-trip, `pyflakes`
clean. Tier 0 now has twenty-one real converted sites.

## [1.34.114] — Tier 0's nineteenth/twentieth conversions: dispute pair + omen subject

Explicit user decision via `AskUserQuestion` on the two sites flagged
as needing a call: both approved.

**Dispute pair pick (nineteenth site).** `Population.due_for_dispute`
previously returned the FIRST eligible festering pair found each tick
and stopped scanning — cheap, but structurally incapable of weighing
candidates. Explicit user decision to accept the added per-tick cost:
now every eligible pair this tick is collected, then a lazy `humans_
lean` callable (an Agent -> confidence lookup, not a precomputed dict
— keeps the actual `humans_pillar.subject_confidence` scan bounded to
the typically-small candidate set, never the whole population every
tick) picks among them via `max`. `max`'s first-max-wins tiebreak
reproduces the exact prior first-found pick when no lean exists
anywhere. Only the chosen pair's cooldown is set, same as before.

**Omen subject pick (twentieth site).** Explicit user decision
extending v1.34.9's one-time Phase G carve-out (previously scoped only
to omen's own `world_model` mirror write) to the subject-candidate
pick itself: the uniform `rng`-index pick among omen subject
candidates (living agents, "the council of elders") is now a weighted
`rng.choices` pick, leaning toward whichever candidate `nature_pillar`
already has standing confidence about (`NATURE_OMEN_SUBJECT_LEAN_MAX
= 0.4`, uniform weight-1.0 floor). Every other Phase G ambiguity rule
is unchanged — this only shifts WHICH already-eligible candidate an
omen might center on, never whether anything supernatural is
confirmed. Honestly often a no-op in practice since Nature's own
content is ecological, not usually agent-or-institution-named — real
when a genuine overlap exists.

Verified: a direct test of `due_for_dispute` (two synthetic festering
pairs, no-lean picks pair-in-scan-order, a seeded lean flips the pick,
only the chosen pair's cooldown is set), production-path tests through
both real scheduling functions (`_maybe_schedule_dispute`/`_maybe_
schedule_omen`, no-lean and seeded-lean cases for each), a 4000-tick
LLM-disabled soak with a clean round-trip, `pyflakes`/syntax clean.
Tier 0 now has twenty real converted sites.

## [1.34.113] — Tier 0's eighteenth conversion: migration decision pick

Explicit user instruction: "Build as many sites as possible in this
turn." `_maybe_schedule_migration_decision`'s candidate pick
(`candidates[0]`, the first in `Population.agents` iteration order)
was simpler to convert than the letter site — `core_migration_
candidates` already returns the FULL eligible list, so only the
engine's pick itself needed to change. Now `max(candidates, key=
lambda c: humans_pillar.subject_confidence(c[0].name))` — the
candidate Humans' own attention already returns to is somewhat more
likely to be this tick's considered migration decision. `max`'s
first-max-wins tiebreak reproduces the exact prior first-found pick
when no lean exists anywhere.

Verified: a production-path test through the real `_maybe_schedule_
migration_decision` (two core-cast agents forced eligible via
`standing_penalty`, the migration-decision roll forced to pass — no-
lean picks whichever agent iteration order favors, a seeded belief
about the other agent flips the pick to them), a 4000-tick LLM-
disabled soak with a clean round-trip, `pyflakes`/syntax clean. Tier 0
now has eighteen real converted sites.

## [1.34.112] — Tier 0's seventeenth conversion: fission leader pick

Explicit user instruction: "Build as many sites as possible in this
turn." `Population.fission_candidate`'s leader pick among already-
`FISSION_LEADER_AMBITION`-eligible candidates (`max(leaders, key=
lambda a: a.traits.get(TRAIT_AMBITION, 0.0))`) had the exact same
shape as `deliberate_guild_candidate`'s founder pick — gained an
optional `humans_lean` param, reusing `GUILD_FOUNDER_HUMANS_LEAN_MAX`
unchanged (same trait scale, no reason to tune differently). Simpler
than the guild site: the eligibility filter here already runs BEFORE
the pick (`leaders` is pre-filtered), so a lean can only reorder among
candidates already known to be ambitious enough — no separate floor
re-check needed. `_maybe_schedule_fission` computes the lean dict from
`humans_pillar.subject_confidence(agent.name)` over all living agents
and passes it through.

Verified: a direct test against a real `Population` built via `spawn_
initial` (no-lean picks the more-ambitious leader; a seeded lean flips
the pick), a production-path test through the real `_maybe_schedule_
fission` (forced monthly gate, same no-lean/seeded-lean cases), a
4000-tick LLM-disabled soak with a clean round-trip, `pyflakes`/syntax
clean. Tier 0 now has seventeen real converted sites.

## [1.34.111] — Tier 0's sixteenth conversion: guild founder pick

Explicit user instruction: "Continue tier 0." `Population.deliberate_
guild_candidate`'s founder pick among tied-eligible masters (`max(...,
key=lambda a: a.traits.get(TRAIT_AMBITION, 0.0))`) was purely trait-
driven with no pillar input. New optional `humans_lean` param (agent_id
-> a small bounded bonus, computed by the caller — `Population`
deliberately doesn't reference pillar state) lets the master Humans'
own attention already returns to edge out a marginally-more-ambitious
rival. New `GUILD_FOUNDER_HUMANS_LEAN_MAX = 0.2` bounds the lean
against traits' `[-1, 1]` range. Critically, the eligibility floor
(`DELIBERATE_GUILD_FOUNDER_AMBITION`) is still checked against each
candidate's REAL, unmodified trait after the pick — a lean can shift
WHO gets considered but can never manufacture a founder who wasn't
genuinely ambitious enough on their own. `_maybe_schedule_guild_
founding` computes the lean dict from `humans_pillar.subject_
confidence(agent.name)` and passes it through.

Verified: a direct test (no-lean picks the more-ambitious master; a
seeded lean flips the pick to the less-ambitious one; a large lean
cannot approve a founder whose real ambition sits below the floor), a
production-path test through the real `_maybe_schedule_guild_founding`
(no-lean vs. seeded-lean cases), a 4000-tick LLM-disabled soak with a
clean round-trip, `pyflakes`/syntax clean. Tier 0 now has sixteen real
converted sites.

## [1.34.110] — Tier 0's fifteenth conversion: letter's sender pick

Explicit user instruction: "Continue." `_maybe_schedule_letter`'s
cross-settlement letter-writer search previously stopped at the FIRST
eligible core-cast sender in `Population.agents`' plain iteration
order — an accident of storage order, not a meaningful choice. Now
every eligible sender in the target settlement is collected (still
each sender's own first qualifying recipient, unchanged), then
`humans_pillar.subject_confidence(sender.name)` picks among them via
`max` — the sender Humans' own attention already returns to is
somewhat more likely to write this month's letter. `max`'s first-max-
wins tiebreak means with no lean anywhere (the common case) this
reproduces the exact prior first-found pick byte-for-byte, verified
directly.

Verified: a production-path test through the real `_maybe_schedule_
letter` (a synthetic two-settlement, two-eligible-sender scenario — the
no-lean case picks the original first-found sender; a seeded Humans
belief about the second sender flips the pick to them), a 4000-tick
LLM-disabled soak with a clean round-trip, `pyflakes`/syntax clean.
Tier 0 now has fifteen real converted sites.

## [1.34.109] — Tier 0's fourteenth conversion: personal_belief's monthly picks

Explicit user instruction: "Continue tier 0." A self-referential site,
same shape as `ontology_evolution`'s Innovation self-lean:
`_maybe_schedule_personal_belief` WRITES `humans_pillar.world_model`
(via `_run_personal_belief`'s apply(), v1.34.98) but its own monthly
candidate draw — `rng.sample(candidates, k=PERSONAL_BELIEF_PICKS_
PER_MONTH)`, uniform without replacement — never READ it.

Converted to a sequential weighted draw without replacement: each
remaining candidate's pick weight is `1.0 + humans_pillar.subject_
confidence(agent.name) * HUMANS_PERSONAL_TARGET_LEAN_WEIGHT`, the
exact same constant every sibling Humans-lean site already uses — no
reason to tune this one differently. `rng.sample` -> sequential
`rng.choices` is a real RNG-consumption-pattern change (documented,
not a violation — same acknowledgment as v1.34.96/108's analogous
conversions) but preserves the DISTRIBUTION: a 20,000-trial check
confirmed near-uniform picks with no lean anywhere.

Verified: a 20,000-trial statistical test (uniform with no lean, a
seeded 0.9-confidence candidate picked noticeably more often), a
production-path test through the real `_maybe_schedule_personal_
belief` (300 forced-gate trials, a max-confidence seeded belief raised
the target's pick rate well above the uniform baseline), a 6,000-trial
no-lean production-path regression test (near-uniform across all core-
cast candidates), a 4000-tick LLM-disabled soak with a clean
round-trip, `pyflakes`/syntax clean. Tier 0 now has fourteen real
converted sites.

## [1.34.108] — Tier 0's thirteenth conversion: voice-pair protagonist pick

Explicit user instruction: "Continue." Audited for a next real site
found by inspection rather than an invented-content design.
`_voice_narrative_extra_scores` (feeds `Population.select_voice_pair`'s
significance ranking — "who's the story about right now") already had
two engine-computed signals (a recent inventor, active COUNCIL
membership); a third real signal was sitting unused: Humans pillar's
own per-agent-name-keyed `world_model` content, already proven
reliable across five prior sites (`memory_drift`/`noncore_nudge`/
`invention`/`ontology_proposal`/`dream`).

New `VOICE_NARRATIVE_HUMANS_LEAN_MAX = 2000.0` bounds how much
`humans_pillar.subject_confidence(agent.name)` (0..1) can add to a
core-cast agent's bonus, same magnitude family as (and deliberately
below) the inventor (4000)/council (3500) bonuses — a standing Humans
theory nudges the weekly protagonist pick, never outweighs a genuinely
dramatic recent event. Scoped to the core cast only, the same pool
`select_voice_pair` filters to. An agent with no standing Humans
theory contributes 0.0, a true no-op.

Verified: a direct test of the extra-scores computation (no-lean
baseline, a seeded 0.8-confidence belief adding exactly 1600.0, non-
core agents unaffected); a production-path test through the real
`Population.select_voice_pair` (baseline pick with no seeded lean, a
max-confidence seeded belief about a different core-cast member
flipping the protagonist pick to them); a 4000-tick LLM-disabled soak
with a clean round-trip; `pyflakes`/syntax clean. Tier 0 now has
thirteen real converted sites.

## [1.34.107] — Tier 0's twelfth conversion: Nature's first site

Explicit user instruction, following v1.34.106's `AskUserQuestion`:
"Species-keyed theory producer (Recommended)." Builds the new Nature
content the prior pass found genuinely missing.

New deterministic mirror inside `_maybe_schedule_nature_mind`'s
apply(): whenever the job's already-computed `wildlife_summary` shows
real pressure (`prey_scarce`, or `predator_pressure_ratio > 0.25`), it
also upserts a SECOND `nature_pillar.world_model` entry keyed by the
literal species word (`"grazer"`/`"predator"`) — computed from Body
state, never the LLM's own free-text answer, so it's a reliable
subject unlike Nature's ordinary belief text. Revised in place via
`find_world_model_entry` across repeated firings rather than piling up
near-duplicates.

Real consumer: `_maybe_schedule_species_variant`'s herd-candidate pick
(previously flatly `min(candidates, key=lambda h: h.id)`) now sorts by
`nature_pillar.subject_confidence(herd.species.value)` (descending),
lowest id as the tiebreak — a species Nature has lately been "worried
about" is now measurably more likely to be the one that gets a named
variant. With no lean anywhere (the common case, since the species
entries only exist after a real pressure signal fired) this reproduces
the exact prior lowest-id pick byte-for-byte.

Verified: a direct test of the producer (writes both entries, revises
in place with no duplicate growth) and the consumer's no-lean/seeded-
lean ordering; a production-path test through the real `_maybe_
schedule_nature_mind` (forced pressure signals, confirmed both mirror
entries form) and the real `_maybe_schedule_species_variant` (seeded
predator lean picks the higher-id predator herd over the lower-id
grazer herd); a separate production-path no-lean test confirming the
exact prior lowest-id pick is preserved; a 4000-tick LLM-disabled soak
with a clean round-trip; `pyflakes`/syntax clean. Nature pillar's
first-ever Tier 0 site. Tier 0 now has twelve real converted sites.

## [1.34.106] — Tier 0's eleventh conversion: Reflection's first site

Explicit user instruction: "Invent new content ask me if needed and
continue tier 0." Investigated both pillars still stuck at zero
conversions. Nature's real `world_model` content is free-text
ecological phrases or fixed hypothesis strings with no reliable match
against any existing WHICH-candidate site — forcing one would repeat
the exact fragile-dead-end shape Humans pillar hit before v1.34.98's
real per-agent producer, so Nature was NOT forced this pass (see the
`AskUserQuestion` below). Reflection turned out to need no invention
at all: `_detect_reflection_pattern`'s subjects are already
settlement-name-keyed (`f"{label} in {settlement.name}"`), so its own
settlement loop was a real, immediately-usable WHICH-candidate site.

When more than one settlement crosses its pattern threshold the same
cycle, the loop used to examine `World.settlements` in plain list
order — an accident of settlement-creation history, not a meaningful
tiebreak. Settlements are now sorted by `reflection_pillar.subject_
confidence(settlement.name)` (descending) before the loop runs: "the
settlement Reflection already has a standing theory about" is examined
first. `list.sort`'s stability means with no lean anywhere (the common
case) this reproduces the exact prior list-order result byte-for-byte
— verified directly, not assumed.

Verified: a direct production-path test (two settlements forced to
cross the same threshold the same cycle; no-lean case picks the
original first-in-list settlement; seeding a Reflection belief about
the second settlement flips the pick to it), a 4000-tick LLM-disabled
soak with a clean round-trip, `pyflakes` clean. Reflection pillar's
first-ever Tier 0 site; Tier 0 now has eleven real converted sites.
Via `AskUserQuestion`, the user approved a genuinely new Nature
content mechanism ("species-keyed theory producer") to unblock
Nature's own first site next.

## [1.34.105] — Tier 0's tenth conversion: dream's dreamer pick

Explicit user instruction: "Continue Tier 0." `_maybe_schedule_dream`'s
monthly round-robin dreamer selection had the exact same WHICH-
candidate `rng.choice(candidates)` shape as `memory_drift`/`noncore_
nudge` — reused the SAME `HUMANS_PERSONAL_TARGET_LEAN_WEIGHT` constant
rather than inventing a fourth Humans-specific weight with no live-
diagnostic reason to tune it differently. "The person Humans' own
accumulated attention already returns to" is now measurably (never
certainly) more likely to be this month's dreamer — a real thematic
fit (dreams surfacing what a community's mind keeps returning to)
while staying mechanically identical to the pattern's other instances.

Verified: a production-path test through the real `_maybe_schedule_
dream` (forced monthly gate/backpressure, a max-weight fake RNG,
confirmed the favored agent's own name appears in the built prompt —
genuinely the chosen dreamer, not merely eligible); a 4000-tick
LLM-disabled soak with a clean round-trip. Tier 0 now has ten real
converted sites.

## [1.34.104] — A12 status answered; Tier 0's eighth/ninth conversions

Explicit user instruction: "Check A12 why it is shown as not done and
progress through tier 0."

A12 answered: per-BUILDING-instance material shipped v1.34.58 (a side
effect of A13's chemistry reactor). The checklist stays unchecked
because the item's own literal scope — per-instance material
GENERALIZED BEYOND buildings (e.g. `Vehicle`) — remains genuinely
unbuilt, and correctly so: no real consumer mechanism exists for a
vehicle's material to convert or matter yet, and inventing one just to
close the checkbox would be exactly the kind of unmotivated addition
the standing "mechanically real, not a stub" discipline warns against.
Not a bug, a deliberately-scoped-open item.

Tier 0: `_maybe_schedule_invention`'s and `_maybe_schedule_ontology_
proposal`'s inventor/first-knower selection converted — both had the
exact `rng.choice(candidates)` WHICH-candidate shape the fifth/sixth/
seventh sites already established. New `INVENTOR_HUMANS_LEAN_WEIGHT=
0.4`: `humans_pillar.subject_confidence(agent.name)` now multiplies
each candidate's base weight of 1.0 via `rng.choices` at both sites —
"the person already notable in the community's own accumulated sense
of them" becomes measurably (never certainly) more likely to be
credited as an invention's inventor. Second real instance shipped
alongside the first in the same batch, same precedent C4 established
for giving a pattern its second instance immediately.

Verified: a direct statistical test of the weighting formula (3000
trials, ~48% lift for a seeded 0.9-confidence agent); a production-
path test through the real `_maybe_schedule_invention` (forced gates/
roll, a max-weight fake RNG confirming the favored agent actually
becomes the recorded knower); a 4000-tick LLM-disabled soak with a
clean round-trip. Tier 0 now has nine real converted sites.

## [1.34.103] — C3 CLOSED: pillars may initiate contact

Explicit user instruction: "Let's complete tier 2 first." Investigation
found Tier 2 ("self-contained mechanism gaps") already fully closed —
every item (A3/A4/A15/A14/A18/A19/A21/A20/A13/A17/B5/C4) is marked
CLOSED, nothing open. Via `AskUserQuestion`, moved to Tier 3's open
items instead: C2 (most spec-named pillar-emitted intentions aren't
pillar-emitted at all — genuinely large, explicitly noted as mostly
blocked on Tier 0's own still-unfinished refactor, ~45 sites
remaining) and C3 ("pillars may initiate contact," the one flagged-
not-attempted half of the player<->pillar chat feature, v1.8.0 shipped
only the player-initiated `/ask/{pillar}` direction). Shipped C3; C2
left flagged rather than forcing a shallow slice through a mechanism
this large.

New `Pillar.initiated_messages` (bounded, same shape as `conversation_
log`) + `push_initiated_message(subject, text, tick, world_model_
entry_id)`: the pillar-to-player direction `record_conversation`
doesn't cover. Zero new LLM cost by construction — `text` is always an
already-formed `world_model` belief's own text, never a fresh
generation; the mechanism is entirely about WHETHER/WHEN to surface an
existing thought, not authoring a new one. New `SimulationEngine.
_maybe_pillar_initiates_contact` (monthly): for each of the five
pillars, if its newest `world_model` entry's confidence crosses
`PILLAR_INITIATE_CONFIDENCE_THRESHOLD` (0.75) and hasn't already been
shared (deduped by `world_model_entry_id`), a real independent monthly
roll (`PILLAR_INITIATE_CHANCE_PER_MONTH`, 0.3) decides whether it
volunteers it this month — same "meaningful, never a certainty" shape
`CARAVAN_CHANCE_PER_MONTH` already uses elsewhere. `GET /pillar/
{pillar}` gained `initiated_messages` in its payload; the existing
"ask a pillar" main-UI panel gained an "unprompted" section showing
the latest one, distinct from the question/answer exchange above it.
New `pillar_initiated` event category (💭 icon, "mind" filter group).

Verified: direct unit tests of `push_initiated_message` (cap, round-
trip, legacy-snapshot backfill with the new fields absent); a
production-path test through the real `_maybe_pillar_initiates_
contact` (a seeded high-confidence belief triggers exactly once, a
repeat call doesn't duplicate, a non-`month_end` tick is a no-op, a
low-confidence belief never triggers); a 4000-tick LLM-disabled soak
with a clean round-trip; `node --check` on the frontend change. No
native module touched.

## [1.34.102] — Tier 5 started: B15.1 replay-hash equivalence test

Explicit user instruction: "Can we build some from tier 5?" Tier 5
(docs/HEARTHBENCH-RUNTIME-2026-07-23.md, HearthBench + the Adaptive
Runtime) is nominally sequenced strictly after Tiers 0-4, but the user
directly asked to begin it now — a genuine decision, not skipping the
sequencing by oversight. Via `AskUserQuestion`, chose the doc's own
first-recommended Runtime item (B15.1) over starting HearthBench's A1
package skeleton or the C5 model passport: "the safety net every later
[runtime] change leans on," and independently useful on its own before
any of the runtime's greenfield scheduling/budget/dormancy machinery
exists.

New `scripts/verify_replay_hash.py`: mechanical proof that, today, the
same seed with the LLM disabled produces byte-identical `World.
to_dict()` state across two fully INDEPENDENT process runs (subprocess
isolation by default — a real process boundary is what a genuine
"same seed on a different run/machine" claim needs to survive; Python
hash randomization, OS scheduling, or any accidental object-identity-
order reliance could only ever surface across that boundary, never
within one process). Mirrors `scripts/verify_native_soak.py`'s
established structure exactly (per-tick hashing via `sort_keys=True`
JSON, standalone script per CLAUDE.md's standing "no automated test
suite" rule) but compares two independent runs of the SAME code path
rather than native-vs-fallback of one run. `--in-process` flag trades
rigor for speed when a quick check is enough.

This is the doc's B15.2 "strict Body, adaptive cognition-breadth"
boundary's actual floor: nothing in Part B (task scheduling, budgets,
dormancy) exists yet to toggle, so this ships the baseline the doc
itself says every later runtime feature must be re-checked against
once one does. Both tracks (HearthBench, the rest of the Adaptive
Runtime) remain otherwise unstarted.

Verified: real subprocess-isolated runs at 400 ticks (2 seeds) and a
full-scale 3000-tick run (matching `verify_native_soak.py`'s own
default ticks), both `MATCH`; an `--in-process` run confirmed the
faster mode also works; a direct check of the divergence-index logic
against a hand-injected mismatched hash sequence, confirming the
failure-reporting path (not just the happy path) is correct.

## [1.34.101] — A16 CLOSED: trade-as-network-flow

Explicit user instruction: "Continue A16." Ships the last of A16's
three named pieces (tech-as-DAG v1.34.99, information-propagation
v1.34.100) — **A16 is now fully closed.**

`Settlement.relations` (settlement/buildings.py) was already a real
weighted inter-settlement graph, seeded at fission and nudged by
cross-settlement dialogue — but every prior consumer (`market_
relation_factor`/`caravan_relation_factor`) only ever read a flat
AVERAGE across it, never a genuine per-pair routing question. New
`world/graph_algorithms.py`'s `build_settlement_trade_graph` (weight
= `max(0.0, relation)`, named settlements only) + `max_flow` (a real
Edmonds-Karp max-flow: repeated BFS augmenting-path search over a
residual graph, generic over any directed dict-of-dicts capacity
graph) are A16's fourth and final algorithm. Real consumer: new
`SimulationEngine._maybe_tick_settlement_trade` (monthly,
deterministic, zero LLM cost — same domain as `_maybe_tick_market_
prices`/caravan's own unconditional trade exchange): finds the named
settlement in the deepest materials surplus (above `SETTLEMENT_TRADE_
SURPLUS_THRESHOLD`, 70% of `MATERIALS_CAPACITY`) and the one in the
deepest deficit (below `SETTLEMENT_TRADE_DEFICIT_THRESHOLD`, 30%),
computes the max flow between them over the relation graph (edges
scaled by `SETTLEMENT_TRADE_CAPACITY_SCALE`), and transfers `min(flow_
capacity, surplus_amount, deficit_gap)` materials from source to sink.

The genuinely distinct case a flat pairwise multiplier structurally
cannot express: a settlement can now supply another it's directly
HOSTILE toward, routed through a third settlement both are warm
toward — real network routing, not just "warmer relation, better
trade." No new UI surface — the transfer logs through the existing
"caravan" event category/feed, same precedent as diplomacy's own
narrated economic contact between settlements.

Verified: a direct unit test of `build_settlement_trade_graph`
(negative relations clamped to 0, unnamed settlements excluded); a
direct unit test of `max_flow` (direct edge, `source == sink`, no
path, unknown node, and the multi-hop routing case — flow correctly
bounded by the bottleneck edge along the only available route); a
production-path test through the real `_maybe_tick_settlement_trade`
with three settlements (source/sink directly hostile, both warm
toward a third "router" settlement whose own materials stayed
untouched — confirming genuine flow, not a direct transfer,
occurred); edge-case tests (zero relations anywhere -> zero transfer,
a single named settlement -> safe no-op, a non-`month_end` tick ->
no-op); a 4000-tick LLM-disabled soak with a clean round-trip. No
native module touched (pure Python, at most `MAX_SETTLEMENTS`=3
nodes, no per-tick hot loop).

## [1.34.100] — A16: information-propagation-as-graph-algorithm

Explicit user instruction: "Continue A16." Ships the second of A16's
two remaining pieces (tech-as-DAG shipped last pass, v1.34.99).

`Population.spread_rumor` — a caravan's outside news, the only rumor
path that seeds several listeners in one call — previously drew every
listener via pure `rng.sample` over the WHOLE living population, with
no regard for who was already close to whoever first heard it, despite
the function's own docstring claiming the news "propagates further
through the existing... gossip contagion." New `world/graph_
algorithms.py`'s `bfs_distances`: a real breadth-first traversal of
the relationship graph (`build_relationship_graph`, only positive-
weight edges count as a social path), returning shortest-hop-distance
from a source to every reachable node — A16's third named algorithm.
`spread_rumor` now draws its first listener uniformly (a genuine point
of contact — could be anyone), then every listener after that via a
distance-weighted draw from `bfs_distances(graph, first.id)`: closer
(fewer hops) is more likely, with a new `RUMOR_BFS_BASELINE_WEIGHT`
floor so a total stranger can still occasionally hear it (matching
`memetics.PROPAGATION_BASELINE_WEIGHT`'s same "news travels beyond a
closed circle" discipline). Deliberately BFS (unweighted hop count)
rather than a weighted shortest-path — a genuinely different axis from
`memetics.propagation_weight`'s single-hop tie STRENGTH; this is "how
many people does it pass through," not "how close is any one tie."

**A16 is now closed on two of its three named pieces** (tech-as-DAG,
information-propagation-as-graph-algorithm); trade-as-network-flow
remains open — a larger lift needing a real inter-settlement
goods-flow mechanic built first (caravans today are settlement-vs-
outside-world, not settlement-to-settlement).

Verified: direct unit tests of `bfs_distances` (chain/branch
transitive reachability over a hand-built graph, zero-weight edges
correctly excluded as non-paths, unknown source); a production-path
statistical test through the real `Population.spread_rumor` (a seeded
10-agent population with a real friend clique vs. isolated strangers —
friends included in 82% of 3000 trials vs. 58% for strangers despite
being outnumbered, confirming the bias); edge-case tests (single-agent,
empty population, count=1, count > population); a 4000-tick
LLM-disabled soak with a clean round-trip. No native module touched
(pure Python, small dict traversal, no per-tick hot loop).

## [1.34.99] — A16: tech-as-DAG, the first real traversal over the Innovation lineage graph

Explicit user instruction: "Start A12." Investigation found A12 as
literally scoped (per-instance `Entity.material` generalized beyond
`Building`) was already audited (v1.34.67) and correctly left
unattempted — no real consumer mechanism exists for a `Vehicle`'s
material to convert or matter, and inventing one just to fill the slot
would violate the standing "mechanically real, not a stub" discipline.
Nothing left to ship under A12's stated scope, so moved to A16, a
genuinely open item with a concrete unbuilt piece.

`InventedConcept.lineage` has been a real DAG since v1.3.19
(`evolved_from`/`merged_from`), but nothing had ever run a genuine
graph *algorithm* over it — `world/ontology.py`'s `_referenced_ids`
(pruning-protection) only reads one hop, never a real traversal. New
`world/graph_algorithms.py`'s `ancestor_ids` (full transitive-closure
walk up the DAG, cycle-guarded) and `shares_lineage` (true if one
concept is any-distance kin of the other, or they share a common
ancestor) are the first real algorithm over this graph — A16's
"tech-as-DAG" piece. Real consumer: `SimulationEngine._maybe_schedule_
ontology_evolution`'s merge-pair selection now rejects a pair that
already shares lineage (bounded 4 retries against the existing
fitness/pillar-lean-weighted pool, then merges the original pair
anyway rather than silently doing nothing) — previously nothing
stopped a concept from being merged with its own parent or sibling, a
degenerate "the idea absorbs itself" case with no narrative sense.
Trade-as-network-flow and information-propagation-as-graph-algorithm
(A16's other two named pieces) remain open — genuinely larger lifts,
since neither has an existing flow-network or contagion-graph
structure to build a first algorithm over yet.

Verified: a direct unit test of `ancestor_ids`/`shares_lineage` over a
hand-built 5-concept lineage (chain + merge, confirming correct
transitive closure and both the "direct ancestor" and "shared
ancestor" kinship cases); a production-path test through the real
`_maybe_schedule_ontology_evolution` with a forced-merge RNG and a
seeded sibling pair, confirming the scheduled prompt actually names
the unrelated pair, not the rejected sibling pair; a 4000-tick
LLM-disabled soak with a clean round-trip. No native module touched
(pure Python, small dict traversal, no per-tick hot loop).

## [1.34.98] — Tier 0: Humans pillar's first per-agent producer, closing two sites

Explicit user instruction: "Continue tier 0, try humans pillar
per-agent producer" — resolving v1.34.97's flagged dead-end by
building the missing piece instead of working around it.

**New producer.** `_run_personal_belief`'s apply() (Reflect(), the
job every agent's own private belief revision goes through) now also
mirrors into `humans_pillar.world_model`, not just `.memory` as
before. Subject is deliberately `target.name` itself — not `parsed
["subject"]`, whatever specific topic the reflection happened to be
about — so this becomes Humans' own standing theory ABOUT a specific
person, distinct from that person's own private beliefs (`Agent.
beliefs`) and from Village's public per-person beliefs (`Settlement.
beliefs`). Revises in place across repeated Reflect() calls for the
same agent via `Pillar.find_world_model_entry` (v1.34.80's exact-
match lookup), so a recurring theory about someone doesn't pile up
near-duplicates. This is Humans pillar's first per-agent-keyed
`world_model` content ever — closes the exact gap v1.34.97 found and
declined to work around.

**Two sites unblocked.** `_maybe_schedule_memory_drift` and
`_maybe_schedule_noncore_nudge` (Tier 0's sixth and seventh
conversions) now weight their monthly target draw by `humans_pillar.
subject_confidence(agent.name)` (`HUMANS_PERSONAL_TARGET_LEAN_
WEIGHT=0.4`, same value and shape as `institution_belief`'s own
conversion) — an agent Humans already holds a standing theory about
is somewhat more likely to be this month's drift/nudge target.
`noncore_nudge`'s candidate can genuinely carry this signal because
`personal_belief`'s own candidate pool falls back to ANY agent with
memories (not only core cast) once no core-cast agent is having a
significant moment — verified directly, not assumed.

Verified: direct unit tests (`upsert_world_model`/`find_world_model_
entry` revision-in-place, non-match reads 0.0); a production-path
smoke test through the real `_run_personal_belief` apply() (a fake-
LLM-result-driven call confirming genuine formation, then a second
call for the same agent confirming revision-in-place rather than a
duplicate entry); a 30,000-trial statistical weighting test for both
target-selection sites; production-path smoke tests through the real
`_maybe_schedule_memory_drift`/`_maybe_schedule_noncore_nudge`
scheduling, driven via the actual async tick loop (`_tick_once()`
under `asyncio.run`) until each genuinely fired; a 4000-tick soak
with a clean round-trip; `pyflakes` clean. No native module touched.
Tier 0 now has seven real converted sites plus this one new producer.

## [1.34.97] — Tier 0: a real dead-end found and correctly not shipped

Explicit user instruction: "Continue tier 0 52 mirror sites." Docs-only
— no code shipped this pass, and that itself is the honest finding.

Extended the fifth site's search technique (every `rng.choice(`/`rng.
choices(` codebase-wide, not just `simulation/engine.py`) to two
candidates sharing the exact same shape as the already-shipped
`institution_belief` conversion: `_maybe_schedule_memory_drift` and
`_maybe_schedule_noncore_nudge` (both a uniform pick among per-agent
candidates, Humans-pillar-owned).

Before implementing either, enumerated EVERY `humans_pillar.upsert_
world_model` call site directly (grep, not assumption) and found
exactly one — `narrative_direction`'s mood-theme mirror, whose subject
is always the settlement's dominant mood theme, never an agent's name.
Unlike Village pillar (real per-person/family-name-keyed subjects via
the `beliefs` job, plus guild/faction names) and Innovation pillar
(concept names via `ontology_proposal`/`invention`/merge/evolve),
Humans pillar's `world_model` currently has NO per-agent-keyed content
anywhere in the codebase. Weighting either candidate site by `humans_
pillar.subject_confidence(agent.name)` would read as a permanent,
silent 0.0 in every real case — a decorative no-op wearing the shape
of a real mechanism, not an actual signal. Correctly not shipped.

This environment still has no live LLM server to empirically confirm
subject content in a real run — re-confirmed directly rather than
assumed: a 20,000-tick LLM-disabled soak produces zero pillar world_
model entries and zero institutions at all, since `_schedule_llm_job`
never fires without a live server (the same standing limitation
D1-D4/D9/D10 already carry). The finding above rests on exhaustive
code-reading of every real call site, not a live measurement, and is
recorded as such.

A genuinely different Humans-pillar-owned target-selection site — or
a first per-agent-keyed Humans world_model producer that would unblock
these two candidates — remains open, not attempted. Tier 0 total
stays at five real converted sites (docs/ROADMAP-2026-07-REMAINING.md
has the full per-site record).

## [1.34.96] — Tier 0's fifth conversion site: institution target selection

Explicit user request: "fresh candidate spotted by inspection." Found
by re-scanning every `rng.choice(` call site in `simulation/engine.py`
for one shaped like the four already-converted sites — a genuine
draw among several eligible options a pillar's own accumulated
attention could plausibly weigh, without ever narrowing the pool or
overriding a harder-computed branch.

`_maybe_schedule_institution_belief`'s `institution = rng.choice(
candidates)` — picking WHICH institution gets examined this month —
fit the pattern, but from a different angle than the first four sites
(which all bias WHAT a decision concludes): this one biases WHICH
target gets picked at all. `village_pillar.subject_confidence(
institution.name)` now multiplies each candidate's base weight of 1.0
(`INSTITUTION_BELIEF_TARGET_LEAN_WEIGHT=0.4`) — an institution the
village already holds a confident recent theory about is somewhat
more likely to be examined again, "the village's own attention
naturally returns to what it's already been thinking about." Every
eligible institution keeps a real, substantial chance regardless; a
candidate with no name (COUNCIL) or no matching entry reads as a flat
1.0, same weight as before.

One honest correction made while implementing this: the site switches
`rng.choice` to `rng.choices(..., weights=...)`, which does NOT
consume the RNG identically even at uniform weights (verified
directly — different draw, different resulting state) — unlike the
first four sites, which only added a multiplicative factor onto an
already-`rng.choices`-based or RNG-free computation. This does not
violate any project discipline: CLAUDE.md's workflow rules explicitly
state determinism/reproducibility is not a requirement here. The
docstring is worded to make the actual guarantee precise (uniform
weights -> uniform *distribution*, not byte-identical draws) rather
than overclaiming parity it doesn't have.

Verified: a direct check that `rng.choices` with equal weights and
`rng.choice` consume the RNG differently (documented, not "fixed" —
it's an accepted, explicitly-permitted difference); a 30,000-trial
statistical test confirming uniform weights give a genuinely uniform
distribution and a real lean shifts it in the expected direction; a
production-path smoke test through the real `_maybe_schedule_
institution_belief` (two real institutions, one given a genuine
recent Village world_model entry via its name, confirmed to read a
higher lean); a 4000-tick soak with a clean round-trip. `pyflakes`
clean. No native module touched.

## [1.34.95] — Tier 0.5 D10 soak + Tier 0's fourth conversion site

Explicit user instruction: "Start tier 0 and try finishing it," then
"Continue and ask questions if you are blocked." Two independent
pieces of real progress; Tier 0's own remaining ~52 mirror-write sites
stay genuinely un-scoped follow-up (see the previous commit's re-audit
— no further safe candidate found without either inventing a new
soft-decision point or the explicit design call this pass resolves).

**Tier 0.5 D10, long-horizon soak re-verification, closed for the
deterministic substrate.** Ran a real 60,000-tick `World.tick()` soak
(LLM disabled, this environment has no live LLM server — same standing
limitation D1-D4/D9 already carry). Pace held flat at ~11.5ms/tick
with no growth trend across the full run (checkpointed every 5,000
ticks), and a full `to_dict()`/`from_dict()` round-trip matched byte-
for-byte at the end — the previous attempt (v1.34.21) was killed at
~10k ticks with no wall-clock budget to finish; this run completed all
60k cleanly. Honest limitation found and recorded, not glossed over:
every pillar's `memory` stayed empty for the entire 60k ticks, because
`_schedule_llm_job` never fires at all with `llm_enabled=False` — an
LLM-disabled soak genuinely cannot exercise D10's real question
("does `Pillar.consolidate()`'s digest-of-a-digest folding stay
coherent after many real consolidation rounds?"), only the
deterministic substrate underneath it. That half of D10 still needs a
live LLM server, same as D1-D4/D9.

**Tier 0's fourth mirror-write -> pillar-authored conversion**
(explicit `AskUserQuestion` answer: "yes, as an additional multiplier
alongside fitness"). `_maybe_schedule_ontology_evolution`'s parent
selection for evolve/merge was a pure `concept_fitness_weight`-
weighted pick; unlike the first three sites (each a final catchall
tiebreak that never touches a harder-computed branch), this one
multiplies a new `innovation_pillar.subject_confidence(concept.name)`
lean directly into the primary fitness signal itself — a genuinely
different shape, deliberately kept low (`INNOVATION_EVOLUTION_LEAN_
WEIGHT=0.3`) so fitness (real "did adopters prosper" measurement)
stays dominant; the lean can only ever ADD up to 30% on top, never
subtract or override. The two signals are real and distinct, not a
duplicate: `fitness_history` reflects measured adoption outcomes,
while the pillar lean reflects Innovation's OWN recorded confidence
about that specific concept (a fresh proposal's initial 0.4, or a
later confirmed/refuted revision from `_record_hypothesis_outcome`) —
a concept can carry one without the other. `pillar_lean=0.0` (the
default, and the only value every prior caller ever used) reproduces
`concept_fitness_weight`'s exact prior output.

Verified: direct unit tests (parity at `pillar_lean=0.0`, monotonic
increase at higher leans, the no-fitness-history neutral-base case
still combines correctly with a lean); a production-path smoke test
through the real `_maybe_schedule_ontology_evolution` scheduling
(two real registered concepts, one given a genuine recent pillar
world_model entry, confirmed to read a higher weight and get
correctly favored); a 20,000-trial statistical test confirming the
real weighted-pick ratio matches the expected weight ratio; a
4000-tick soak with a clean round-trip. `pyflakes` clean. No native
module touched.

## [1.34.94] — A10: closes the field-substrate fold-in

Explicit user instruction: "Complete and finish A10 with all remaining
items." The one item still flagged after v1.34.93 was the fold-in's
own one-directional gap: `scent` (predator-pack presence, `World.
fields`) had exactly one consumer anywhere — the human-side
`_choose_fission_site` avoidance — no wildlife-side field folded
predator danger back into GRAZER behavior at region scale.

New `SCENT_REGIONAL_AVOIDANCE_MAX=0.4` (`world/wildlife.py`):
`WildlifeGrid.tick`'s existing GRAZER move-candidate weighting gains a
fourth multiplicative term, weighting away from a region with a high
`scent` reading. Deliberately layered ON TOP of (not replacing) the
existing hard `GRAZER_FLEE_RADIUS` local flee response — that stays a
tile-local, immediate reaction to a live predator pack; this is a
softer, region-scale sense of "a generally dangerous stretch of
country" extending beyond the flee radius's hard cutoff. `scent=None`
(the default, and every existing/legacy call path) reproduces the
exact prior RNG-consumption pattern byte-for-byte.

This closes both flagged directions of the field-substrate fold-in:
wildlife reads `population_density` (v1.34.92), humans read the new
`wildlife` field (v1.34.93), and now wildlife reads `scent` back too
— every field the fold-in named has a real, verified, reciprocal
consumer. **A10 is now fully closed**, including the field-substrate
extension beyond the five originally-named det_sys.md pieces.

Verified: a direct parity test (500-tick identical trajectories with
`scent` omitted vs. explicit `None`); a direct weight-formula
statistical test (20,000 trials, safe/dangerous pick ratio matched the
expected weight ratio to within noise); a production-path statistical
test through the real `WildlifeGrid.tick()` on a synthetic uniform-
grassland terrain (a herd placed at a region boundary crossed into a
scent-flagged region measurably less often than a no-scent control —
0.169 vs. 0.244 crossing rate over 3000 trials); a 4000-tick soak
through the real `World.tick()` with a clean `to_dict()`/`from_dict()`
round-trip; `pyflakes` clean. No native module touched, no native soak
needed.

## [1.34.93] — A10: second slice of the field-substrate fold-in

Explicit user instruction: "Continue A10." Closes the other direction
of the bidirectional coupling v1.34.92 started — that slice made
wildlife READ a human-written field (`population_density`); this one
makes humans READ a wildlife-written field back.

New `FieldGrid.step_wildlife` (`world/fields.py`): sums live GRAZER-
herd sizes per region (same shape `step_scent` already established for
PREDATOR positions), normalized against the richest region, spread via
`ca_operators.diffuse`. Deliberately the POSITIVE counterpart to
`scent`'s existing danger signal — `scent` sources from predator packs
and reads as a threat `_choose_fission_site` avoids; `wildlife` sources
from grazer herds and reads as an opportunity. Wired into `World.tick()`
right after the existing `step_scent` call.

Real consumer: `Population._maybe_welcome_migrant` gained a
`region_wildlife` param + `MIGRANT_WILDLIFE_PULL=0.2` — a fifth
positive region-field pull alongside `ownership`/`cultural_influence`/
`beauty`'s siblings, "word travels that a place has good hunting."
`region_wildlife=None` (the default, and every existing/legacy call
path) is a genuine no-op — the chance formula only applies the term
when the field is present, matching every sibling pull's own
discipline.

UI: new "wildlife" (labeled "game presence") mode on the existing
"🗺️ fields" overlay toggle, own gold-to-forest-green "opportunity"
color ramp deliberately distinct from `scent`'s danger-red family, plus
a matching legend entry. Threaded through both `WorldBroadcaster.
set_terrain`'s two real call sites in `simulation/engine.py` (checked
deliberately — this project's own standing "one call site missing a
field" bug class, first caught at v1.34.75) and `interface/api.py`'s
payload dict.

Verified: direct unit tests for `step_wildlife` (no-grazer neutral
parity, real gradient formation, normalized-peak shape); a production-
path test through the real `World.tick()` confirming the field forms
organically from real grazer herds over 1500 ticks; a legacy-backfill
test (a snapshot missing the `wildlife` key entirely loads clean, reads
neutral, and repopulates on the next tick without crashing); a 4000-
tick soak with a clean `to_dict()`/`from_dict()` round-trip; a direct
`WorldBroadcaster.set_terrain` test confirming the payload key is
present with real values and gracefully empty when the kwarg is
omitted; `node --check` and `pyflakes` clean on every touched file. No
native module touched, no native soak needed.

## [1.34.92] — A10: first slice of the field-substrate fold-in

Explicit user instruction: "Continue A10." With all five named
det_sys.md pieces shipped (v1.34.87-.91), the only A10 item left is
"fold the existing food web onto A1's field substrate as one coupled
system" — explicitly flagged as larger/unscoped. Ships a real first
slice rather than attempting the whole thing at once.

Audited every existing wildlife-side field consumer (`nutrients`,
`scent`, `noise`) and found each reads a field that's either ecology-
internal or generic — none read a field the HUMAN/settlement side
writes. `World.fields`' `population_density` (A1's own first-shipped
field) had no wildlife-side consumer at all. New `WildlifeGrid.tick`'s
`population_density` param: a GRAZER herd's move candidates are now
down-weighted in a heavily populated region (`WILDLIFE_POPULATION_
AVOIDANCE_MAX=0.6`, floored so the combined weight is never zero),
combined multiplicatively with the existing trail-preference and
nutrient-pull terms. "Wildlife shies from busy human areas" closes a
real two-way coupling — humans already read a wildlife-adjacent field
back (`scent`, fed by predator positions, dampens `_choose_fission_
site`'s odds of landing near a dangerous pack) — the first genuine
bidirectional link between the two sides of "the food web" and "the
field substrate," not just wildlife consuming ecology-internal
signals.

`population_density=None` (the pre-this-slice default) reproduces the
exact prior RNG-consumption pattern byte-for-byte — verified directly,
same discipline every sibling field param in this function already
holds.

Verified: a direct parity test (500-tick identical trajectories with
`population_density` omitted vs. explicit `None`); a weight-floor
check (never reaches zero even at full saturation); a production-path
statistical test through the real `WildlifeGrid.tick()` on a 60x60
map with a genuine population-density gradient — herds given the real
gradient ended up in the crowded region less than a third as often
(2/40 seeds) as herds given a flat field with no avoidance pressure
(6/40), a real, reproducible avoidance effect; a 4000-tick `World.
tick()` production soak (LLM disabled) with a clean round-trip.
`pyflakes` clean. No native module touched.

Folding the REST of the food web onto the field substrate (a wildlife-
presence field of its own, predator/prey coupling into more fields,
etc.) remains open — this is a first slice, not a claim of closure on
the larger item.

## [1.34.91] — A10: migration (resource-pressure-driven movement)

Explicit user instruction: "Continue A10." Ships A10's migration
slice — the last of the five named pieces (decomposition/pollination/
competition/habitat-formation shipped v1.34.87-.90). Before this
pass, GRAZER movement already had two real biases (M4's trail-reuse
preference, predator-avoidance) plus a separate seasonal leave-the-
map/recolonize abstraction, but nothing modeling real population
redistribution toward better resource areas — the actual ecological
sense of "migration" det_sys.md names.

`WildlifeGrid.tick`'s existing move-candidate weighting (already
used for M4's trail preference) now also weights each candidate tile
by its own `World.fields` `nutrients` reading — new `MIGRATION_
NUTRIENT_PULL_WEIGHT=2.0` — combined MULTIPLICATIVELY with the trail-
preference weight when both apply, so a candidate that's both an
established crossing and nutrient-rich is doubly preferred rather
than an either/or choice. `nutrients=None` (the pre-slice default —
still the shape most direct callers use) reproduces the EXACT prior
RNG-consumption pattern: trail-only weights if `migration_trails` is
set, otherwise a plain uniform `rng.choice`, verified directly rather
than assumed.

Verified: a direct parity test confirming `nutrients=None`/
`migration_trails=None` produces byte-identical herd trajectories to
omitting both params entirely across 500 ticks; a direct weight-
formula check; a production-path statistical test through the real
`WildlifeGrid.tick()` on a 60x60 map with a genuine nutrient gradient
(a rich corner vs. flat/poor elsewhere) — herds given the real
gradient ended up in the rich region more than twice as often (13/40
seeds) as herds given a flat field with no pull (6/40), a real,
reproducible drift effect, not noise; a 4000-tick `World.tick()`
production soak (LLM disabled) with a clean round-trip. `pyflakes`
clean. No native module touched — movement selection has never been
natively ported.

**A10 "Ecology / food webs" is now closed on every named piece from
det_sys.md's own spec** (migration, competition, decomposition,
pollination, habitat formation) — only "fold the whole food web onto
A1's field substrate as one coupled system" remains, an explicitly
larger, unscoped follow-up, not attempted.

## [1.34.90] — A10: habitat formation (fields write carrying capacity)

Explicit user instruction: "Continue A10." Ships A10's habitat-
formation slice — det_sys.md's own wording, "habitat formation (reads
fields, writes carrying capacity)" — following v1.34.87-.89's
decomposition/pollination/competition slices. The one A10 axis that
had NO real implementation of any kind before this pass (every other
named piece had at least a partial slice).

New `world/wildlife.py`'s `habitat_capacity(nutrients_at, base=
MAX_HERD_SIZE)`: a region's real standing wild-food abundance
(`World.fields`'s `nutrients` field — the same signal `NUTRIENTS_
REPRODUCE_BONUS_MAX` already reads for reproduce CHANCE) now also
raises how large a herd that habitat can sustain before crowding
stops growth, up to `HABITAT_CAPACITY_BONUS_MAX=0.5` (50%) past the
flat `MAX_HERD_SIZE` baseline in a fully nutrient-rich region.
Deliberately a pure bonus, never a penalty below baseline:
`nutrients_at=0` (no field data, or a genuinely barren region)
reproduces the exact flat cap, byte-for-byte — the same "field
absence means neutral, never worse" discipline every other `World.
fields` consumer in this module already holds, verified directly.
Wired at both cap-check sites (the native fast path's `MAX_HERD_SIZE`
argument and the pure-Python fallback's `herd.count <
MAX_HERD_SIZE` check) via one shared `effective_max_herd_size`, so
both paths stay in lockstep — no native-module signature change
needed, since `effective_max_herd_size` is just a differently-valued
plain int handed to the same existing native call.

Verified: direct unit tests (`nutrients_at=0` exact-parity with the
flat baseline, the full-bonus value at `nutrients_at=1`, monotonic
in between, a floor-of-1 defensive check); a production-path test
through the real `WildlifeGrid.tick()` (a herd starting AT the flat
cap in a fully nutrient-rich region genuinely grows past it — 12 to
13 — over 4000 ticks with movement frozen to isolate the effect; a
control run with no `nutrients` field passed confirmed the herd never
exceeds the flat cap, proving the bonus is genuinely additive, not a
silent baseline shift); a 4000-tick `World.tick()` production soak
(LLM disabled) with a clean round-trip. `pyflakes` clean. No native
module touched.

## [1.34.89] — A10: competition (intraspecies crowding penalty)

Explicit user instruction: "Continue A10." Ships A10's competition
slice — det_sys.md's own "competition" line, following v1.34.87's
decomposition and v1.34.88's pollination slices. Intraspecies
competition: multiple live GRAZER herds sharing the same tile are
genuinely competing for the same limited forage, distinct from
`grazing_food`/`overgrazed` (which model the food SOURCE depleting,
not herds crowding each other out for access to it).

New `WildlifeGrid.tick`'s `grazer_tile_counts` (computed once up
front from PRE-movement herd positions, same "cheap O(n) aggregate,
not a new per-herd hot loop" discipline the existing trophic-pressure
aggregates in this function already use): each GRAZER herd's own
`reproduce_chance` now carries an additional `competition_factor`
term — `COMPETITION_PENALTY_PER_RIVAL=0.15` shaved off per rival herd
sharing its tile, floored at `COMPETITION_MIN_REPRODUCE_FACTOR=0.4` so
crowding pressures reproduction without ever hard-locking it. A herd
alone on its own tile (the overwhelming common case) gets `rivals=0`
→ `competition_factor` exactly `1.0`, a genuine mathematical no-op —
verified directly rather than assumed. Folded into the single
`reproduce_chance` float both the native fast path (module 22) and
the pure-Python fallback already consume identically, so this needed
no native-module signature change and carries zero native/fallback
parity risk.

One real design bug caught and fixed during this slice's own
implementation (not by the user): the rival lookup initially keyed
off `herd.x`/`herd.y` AFTER this tick's own movement step, but
`grazer_tile_counts` was built from PRE-movement positions — a
mismatched snapshot. Fixed by capturing `pre_move_pos = (herd.x,
herd.y)` at the top of the per-herd loop, before movement can change
it, and keying the rival lookup off that instead.

Verified: direct unit tests (competition-factor formula bounds, floor
respected under many rivals, solo herd reads exactly 1.0); a
production-path test through the real `WildlifeGrid.tick()` (movement
frozen via a monkeypatched `MOVE_CHANCE=0` to isolate the effect,
solo vs. 4-rival herds compared over 60 seeds each — solo averaged
3.03 growth vs. crowded's 1.07, a clear, real, reproducible effect);
a 4000-tick `World.tick()` production soak (LLM disabled) with a
clean `to_dict`/`from_dict` round-trip. `pyflakes` clean. No native
module touched — `reproduce_chance` stays a plain float handed to the
existing native fast path unchanged.

## [1.34.88] — A10: pollination (wildlife-fed succession pressure)

Explicit user instruction: "Continue A10." Ships A10's pollination
slice — det_sys.md's own "pollination (→ vegetation)" line, the third
of A10's five named unbuilt pieces (migration/competition/
decomposition/pollination/habitat-formation), following v1.34.87's
decomposition slice.

Extended the existing A2 succession-pressure mechanism
(`terrain_evolution.compute_succession_pressure`, already blending
forest density + moisture to modulate how fast an abandoned tile
returns to forest) with a new optional `grazer_positions` param: a
live GRAZER herd's current tile diffuses outward into a small
"pollination/seed-dispersal" field (`ca_operators.diffuse`, same
composition `forest_density` already uses) and adds a genuine, capped
bonus (`POLLINATION_BONUS_MAX=0.15`) on top of the existing reading —
"animals carry seeds and pollen as they move through a landscape."
Threaded through `maybe_reclaim` to `World._tick_terrain`'s call site,
sourced from `self.wildlife.herds` (live GRAZER herds only).

**Real bug caught and fixed during this slice's own verification,
before shipping**: the first implementation blended pollination in as
a weighted average (`base*(1-w) + pollination*w`) rather than an
additive bonus — since "no wildlife here" reads as `pollination=0`,
that blend silently LOWERED succession pressure by 15% on every tile
with no nearby wildlife, not just leave unaffected tiles alone. A
direct test asserting "a far tile should be ~unaffected" caught this
immediately (a 0.03 unexpected delta on a tile nowhere near the test
herd). Fixed to a straightforward additive+capped bonus — a tile with
no nearby grazer now reads EXACTLY as it did before this param
existed, verified directly.

Verified: direct unit tests (no-grazer-positions parity against the
pre-pollination result, a real bump at/near a herd's tile with a
verified-unaffected far tile, result bounds, the `moisture=None`
fallback path unaffected by `grazer_positions`); a production-path
test through the real `World.tick()`/`_tick_terrain` call chain (real
grazer herds present, no crash, clean round-trip) over a 4000-tick
LLM-disabled soak. `pyflakes` clean. No native module touched — this
extends an already-pure-Python R2 mechanism (`compute_succession_
pressure` has never been natively ported).

## [1.34.87] — A10: decomposition (carcass-fed nutrient pulse)

Explicit user instruction: "Check for other performance implications
and fix them. Start A10 after that." Performance audit: grepped every
`_tick_once()` call site across the codebase — confirmed `simulation/
sandbox.py`'s two loops (both fixed in v1.34.86) were the ONLY place
in the whole tree looping a synchronous tick multiple times inside an
async function; no other instance of that bug class exists. Nothing
further found or changed.

A10 "Ecology / food webs" (roadmap Stage IV step 17), decomposition
slice — the doc's own named gap distinct from the already-shipped
predator-prey feedback and live-herd nutrient cycling
(`economy.farms.apply_nutrient_cycling`, an ongoing, small, per-tick
dung enrichment from a grazing herd). Decomposition is a different
nutrient SOURCE: a real carcass left by a successful predator kill,
a discrete one-time pulse rather than an ongoing trickle.

New `world/terrain_evolution.py`'s `apply_carcass_decomposition`/
`decay_carcass_decomposition` — same additive-capped/weekly-decay
scar-shaped-dict pattern as `road_scars`/`migration_trails`/
`dry_lakebed_scars`, but a single kill already clears the visible
threshold on its own gain (unlike `migration_trails`' tiny per-step
gain needing many reused crossings) since a kill is a genuinely
discrete event, and decays faster (~5 weeks vs. migration trails'
~9) since an actual carcass is consumed away quicker than a worn
habit fades. New `World.carcass_decomposition` (persisted, legacy-
backfill-safe via `dict.get(..., {})`), gained via `WildlifeGrid.
tick`'s new optional `carcass_decomposition` param (`None` reproduces
the exact prior RNG stream and behavior byte-for-byte — verified
directly) at the real predator-kill site. New `economy/farms.py`'s
`apply_carcass_decomposition_bonus` — the decomposition-side
counterpart to `apply_nutrient_cycling`, same weekly cadence
(`World._tick_disasters`), reading the position-keyed decomposition
dict directly rather than iterating live herds, scaled stronger
per-unit-intensity than the live-herd rate to reflect a real carcass
being a concentrated source, still bounded per tick.

UI: new rust-red `paintCarcassDecomposition` map layer (distinct
color from every other scar), "Carcass decomposition" main-UI stat
tile, bare-tile inspector "Carcass" section — `interface/api.py`'s
`set_terrain` payload and BOTH of `engine.py`'s call sites gained the
new field together (the exact "one call site missing a field" bug
class v1.34.75 found and fixed once already, checked deliberately
this time rather than repeated).

Verified: direct unit tests (`apply_carcass_decomposition`'s single-
kill-crosses-threshold/additive/capped behavior, `decay_carcass_
decomposition`'s decay-then-delete, `apply_carcass_decomposition_
bonus`'s radius-gated bonus and no-op-on-empty-input cases); a
production-path test through the real `WildlifeGrid.tick()` (forced
predator/grazer colocation, confirmed a real kill populates
decomposition through the actual mechanism) plus a direct `None`-vs-
omitted parity test confirming byte-identical RNG stream/behavior; a
real 4000-tick `World.tick()` production soak (LLM disabled)
confirming organic formation (1 site) through the actual engine, a
clean `to_dict`/`from_dict` round-trip, and a legacy-snapshot
backfill test (`carcass_decomposition` key absent entirely); a live
dev server + `curl` pass confirming `carcass_decomposition` reaches
both `/terrain` and `/state`'s `summary` in the real payload shape.
`node --check` clean. No native module touched.

## [1.34.86] — Fix: A8's dual-fork froze the real event loop for seconds

Direct user follow-up question on v1.34.85: "Would this worsen the
back pressure drop or slow the simulation down? The forking." A live
investigation, not a guess: `evaluate_concept_dual_fork`'s (and the
pre-existing `run_counterfactual`'s) inner `for _ in range(ticks):
engine._tick_once()` loop had no `await` point anywhere inside it.
Measured `_tick_once()` at ~12ms/tick on a small forked population —
the dual-fork's two 150-tick forks meant ~3.5 real seconds where the
loop never returned control to the event loop at all. Confirmed via a
direct benchmark: because Python/asyncio is single-threaded, this
fully froze the REAL engine's tick loop (its own `run_forever` yields
between ticks via `await asyncio.wait_for(...)`, so it genuinely can't
run until the fork's loop yields something back), any pending LLM I/O
completion, and the WebSocket broadcaster — not a backpressure-counter
effect (LLM is disabled inside the fork, so `CognitionRunner`'s
concurrency/backlog counters are untouched), but a real multi-second
stall of the live simulation and its API surface each time a concept
retirement fires the dual-fork check.

Fixed by adding one `await asyncio.sleep(0)` per tick inside BOTH
loops (`run_counterfactual`, which had the identical shape at half the
cost, and the new `evaluate_concept_dual_fork`) — negligible overhead
against a ~12ms tick, but turns a hard freeze into cooperative
interleaving: the real engine's own scheduled wakeups can now run
between fork ticks instead of only after all of them finish. Doesn't
change the fork's own total wall-clock cost, only stops it from also
freezing everything else.

Verified: a direct concurrency test (`asyncio.gather`'d the dual-fork
against a 2000-iteration counter coroutine that also yields every
iteration) confirmed the counter now completes all 2000 iterations
DURING the fork's run — before the fix this would have been ~0
(frozen until the fork finished); a 4000-tick LLM-disabled soak with
clean round-trip; the existing dual-fork/reinstatement unit tests
re-run unmodified, all still passing.

## [1.34.85] — A8: the comparative dual-fork (causal concept-retirement check)

Explicit user instruction: "Take dual fork of A8" — the heavier
mechanism v1.34.84's investigation flagged as the only way to make
"sandbox forward-simulation as a fitness input" genuinely meaningful,
rather than the vacuous acceptance-gate approach that pass correctly
declined to ship.

Re-audited the "mechanical_hook is never consumed" finding before
building anything on top of it, since a provably-zero-effect state
would make ANY dual-fork comparison always diff to zero — found it
was incomplete, not wrong: `mechanical_hook` genuinely is inert, but
`InventedConcept.adopter_ids` is NOT — `World.tick()` unions every
concept's adopters settlement-wide into `FieldGrid.step_cultural_
influence`, which gives `Population._maybe_welcome_migrant` a real
positive `MIGRANT_CULTURAL_PULL` pull in the region(s) adopters stand
in (v1.34.62). A concept's real adoption footprint DOES causally
shape simulation dynamics — just diffusely, through migration
pressure, not through the hook vocabulary.

New `simulation/sandbox.py`'s `evaluate_concept_dual_fork(world,
config, concept_id, ticks=CONCEPT_FITNESS_SANDBOX_TICKS=150)`: forks
the world twice from one shared `World.to_dict()` snapshot — once
with a concept's real current `adopter_ids`, once with that one
concept's adopters stripped to empty — and runs both forward
(LLM disabled, same disposable-fork discipline as the existing
`run_counterfactual`), returning `population_with - population_
without`. The reasoning for why a nonzero delta is a genuine causal
signal rather than two independently noisy runs: every RNG draw in
this codebase is `_namespaced_rng`/`_namespaced_roll`, keyed by
`(seed, tick_count, ...)`, never call order — both forks share the
identical seed and starting snapshot, so every roll VALUE is
identical between them right up until a roll that itself reads
`cultural_influence` straddles a threshold the two forks' differing
field values put on opposite sides. A population difference is that
threshold tipping, not sampling noise. `ticks=150` (3x `SANDBOX_
TICKS`) gives a population-mediated effect real time to compound into
a visible headcount difference, unlike the fast crash/explosion
invariant checks the existing single-fork sandbox looks for.

New `world/ontology.py`'s `reinstate_concept(world, concept_id, tick)`:
deliberately does NOT touch `run_selection`'s existing correlational
retirement (adopter reputation vs. settlement average, immediate/
synchronous) — that stays exactly as it was, load-bearing behavior
left unregressed. This is a SLOWER, SECOND opinion that can reverse a
retirement after the fact: flips `status` back to `established`,
resets `fitness_history` to empty (the readings that triggered the
retirement are now known, by this stronger causal check, to have been
misleading — letting them count toward a second future retirement
would trust the same discredited signal twice), and re-runs `_record_
hypothesis_outcome(..., confirmed=True)`, which revises the SAME
mirrored Innovation `world_model` entry the original retirement's
`confirmed=False` call wrote (both key off `concept.world_model_
entry_id`) — the belief ends up reading as confirmed, not stuck on
its own earlier refutation. Only acts on a concept that is currently
`"retired"`; a no-op (`None`) otherwise (already re-evaluated into a
different status by a later sweep, or no longer exists).

Wiring, `simulation/engine.py`'s `_maybe_schedule_ontology_proposal`:
snapshots the set of `retired` concept ids immediately before and
after the existing synchronous `ontology.run_selection(...)` call
(unchanged itself); each id newly present in the "after" set gets a
new `_confirm_concept_retirement(concept_id)` fire-and-forget
background task scheduled, same `_background_tasks`/`add_done_
callback` lifecycle every other sandboxed proposal (`rule_propose`,
`composite_reaction_propose`) already uses. The task awaits the dual-
fork check; a positive delta (measurably worse off without the
concept's real adopters) reinstates and logs a new `ontology_
reinstated` event + Innovation pillar memory + Emergence API entry;
zero or negative leaves the correlational retirement standing. UI:
new `ontology_reinstated` entry in `app.js`'s `CATEGORY_META`
(♻️, "mind" filter group) — the standing per-batch UI-surfacing rule.

Verified: direct unit tests for `evaluate_concept_dual_fork` (no-
adopters case returns `None`, nonexistent-concept case returns
`None`, a real with-adopters fork pair runs end-to-end and returns a
float, neither fork mutates the real `world`/its `concept.
adopter_ids`) and `reinstate_concept` (non-retired concept is a
no-op, a real retired concept reinstates with `fitness_history`
cleared); a production-path test through the real `_confirm_concept_
retirement` wiring (a forced positive delta reinstates end-to-end
through the actual background-task/`asyncio.gather` path, a forced
negative delta leaves the concept retired); a direct test of the
real `run_selection`-retirement-diff detection logic (a concept
engineered to cross the unfitness threshold is correctly captured in
`newly_retired`); a 4000-tick LLM-disabled engine soak with a clean
`World.to_dict()`/`from_dict()` round-trip. No native module or its
call signature touched, so `scripts/verify_native_soak.py` wasn't run
this pass.

## [1.34.84] — A7: layout-domain lineage grammar; A8 investigated, not shipped

Explicit user instruction: "Start A7 and A8" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 3).

**A7, layout domain — closed.** Of the three A7 domains, layout was
the one flagged as having zero lineage awareness: `settlement_layout_
style(settlement_id)` was (and, for a settlement with no lineage,
still is) a flat `settlement_id % 3` hash, completely uncorrelated
with fission ancestry — unlike dialect's already-recursive `drift_
term`(`steps`) or architecture's per-instance descriptor. New
`Settlement.layout_style: str | None` (persisted; `None` — the
default for the founding settlement and every legacy snapshot — reads
through `effective_layout_style` as the exact original hash, zero
migration needed) and `world/layout_grammar.py`'s `drift_layout_style`:
a real one-generation production rule over the same small closed
`LAYOUT_STYLES` alphabet — usually keeps the parent's style exactly
(`LAYOUT_DRIFT_STAY_WEIGHT=2`, ~2:1 odds), occasionally rewrites to
the next style in the fixed cycle. Wired at the one real site with
lineage, fission's apply() (`_maybe_schedule_fission`): `new_
settlement.layout_style = drift_layout_style(home.effective_layout_
style, seed=f"{new_id}:layout")` — a lineage several fissions deep can
now end up visibly further from its founding settlement's spatial
tradition, applied incrementally generation-by-generation (each
fission reads its own immediate parent's already-resolved style)
rather than a single steps-scaled reapplication. All three existing
consumers (`Population._choose_build_site`'s site-scoring, `Settlement.
summary()`'s "Layout" stat tile, the building-descriptor diagnostics
line) switched from calling the bare hash function to reading `.
effective_layout_style` — no UI change needed, the same existing "Layout"
tile now reflects real lineage-derived data instead of an id hash.

**A8 — investigated, not shipped.** Wiring `simulation/sandbox.py`'s
`run_counterfactual` as an acceptance gate on `ontology.register_
concept` (the literal, cheapest reading of "sandbox forward-simulation
as a fitness input," mirroring `TriggerRule`/`CompositeReaction`'s
existing pre-registration sandbox pattern) turns out to be a real-code-
but-vacuous-signal problem, not a scoping problem: `InventedConcept.
mechanical_hook` is validated at generation time (A5/A6) but never
actually consumed/applied to `World` state anywhere — unlike its
sibling proposal systems, nothing calls `_apply_trigger_rule_hook` for
it. Even granting it that consumption, `_apply_trigger_rule_hook`'s
own docstring already documents only `belief_confidence_bonus` as a
real numeric effect (the rest are explicitly narrative-only by prior
deliberate decision) — a one-time belief-confidence bump structurally
cannot trip the sandbox's population-crash/-explosion or materials-
explosion invariants within `SANDBOX_TICKS` (50), so the gate would
report "safe" unconditionally regardless of what's proposed. Shipping
that would be worse than not shipping it — a rubber stamp dressed as a
real safety check. A genuinely meaningful version needs a different
mechanism (a comparative dual-fork: run forward WITH vs. WITHOUT a
concept's current adopters, diff a real prosperity/carrying-capacity
outcome) — a materially larger lift, explicitly flagged rather than
attempted. Grammar-based mutation as an alternate generate path (A8's
other named piece) depends on A7 reaching a genuine shape-grammar
stage first, which it hasn't — also open. Filed as an explicit
investigation finding in the roadmap, same "don't force vacuous code
through a real-looking gate" discipline as A17's v1.34.59 entry.

Verified (A7 only — A8 shipped no code): direct unit tests for `drift_
layout_style` (stay/drift ratio ~2:1 over 3000 trials, cycle wrap
correctness, invalid-style fallback); `Settlement.layout_style`/
`effective_layout_style` round-trip tests (real value preserved,
`None` falls back to the hash function, a legacy snapshot missing the
key entirely backfills correctly); a direct test of the exact fission-
site code shape (parent's `effective_layout_style` feeding `drift_
layout_style` into the daughter's own `layout_style`); `pyflakes`
clean; a 4000-tick LLM-disabled soak with a clean round-trip. Pure
Python, no native module touched.

## [1.34.83] — Tune: lower LLM_PRESSURE_SLOWDOWN_START_RATIO 0.75 -> 0.5

Explicit user directive, continuing the same backpressure-drop
investigation: "I am okay with occasional slow world progression so
do that" — accepting the tradeoff CLAUDE.md flagged after v1.34.81/
.82's structural fixes: the remaining lever is genuinely a pacing
knob, not a bug.

Root issue: at low integer concurrency (`llm_max_concurrent=1` gives
a static `_backpressure_limit` of `BACKPRESSURE_BACKLOG_PER_SLOT * 1`
= 3), `llm_pressure_ratio()` can only take values `k/3` (0, 0.33,
0.67, 1.0, ...). The old 0.75 threshold sits strictly between 0.67
and 1.0 — a backlog of 2 (already effectively saturated for a single-
inference-slot server: one call executing, one queued) read as ratio
0.67 and engaged NO slowdown at all; only a backlog of 3 — the exact
point new attempts start getting dropped — crossed 0.75. Once
v1.34.81/.82 closed the two structural over-counting bugs, this
reachability gap became the dominant remaining source of genuinely
distinct drops: a fresh scheduling attempt landing on backlog=2 saw
no pacing, immediately pushed the backlog to 3, and became the very
next attempt that gets rejected.

`LLM_PRESSURE_SLOWDOWN_START_RATIO` 0.75 -> 0.5: now a backlog of 2
(ratio 0.67 > 0.5) engages real slowdown (~1.56x tick-gap stretch at
this concurrency, verified directly) BEFORE the queue is completely
full, giving in-flight calls genuine extra real time to drain before
the next wave of scheduling attempts lands — the explicit tradeoff
requested (slower world-time progression under sustained pressure, in
exchange for fewer wasted/dropped attempts). The speedup band (`LLM_
PRESSURE_SPEEDUP_START_RATIO=0.15`) and a real "just right" 1.0x zone
(0.15-0.5, was 0.15-0.75) both survive unchanged; a healthy idle or
lightly-loaded run is unaffected. `REASONING_LOAD_SHED_RATIO`'s
docstring (which referenced the old 0.75 as a sizing anchor) updated
to match — its own value (0.9) is untouched, still comfortably clear
of the new 0.5.

Verified: a direct check of `_llm_pressure_interval_multiplier()`
across the concurrency=1 backlog curve (0/1/2/3/4 -> ratio 0/0.33/
0.67/1.0/1.33 -> multiplier 0.40/1.00/1.56/2.67/3.78), confirming
backlog=2 now genuinely slows ticking where it previously didn't;
`pyflakes` clean; a 4000-tick LLM-disabled soak with clean round-trip
(a pure constant/docstring change — no persisted state, no native
module touched).

## [1.34.82] — Fix: season/year retry-window jobs also re-checked every tick, not once/day

Explicit user follow-up: "Any more things we can do to reduce
backpressure drop [rate]?" — continuing the same investigation as
v1.34.81, looking for the same bug CLASS at other call sites rather
than assuming the nature triggers were the only instance.

Found a second, structurally identical instance: `_season_year_gate`
(the season/year-cadence counterpart to `_monthly_gate`, backing
`SEASON_YEAR_JOBS_WITH_RETRY` — `tradition`/`religion`/`narrative_
direction`/`culture_digest`/`documentary`/`institution_culture`/
`invention`/`ontology_proposal`/`ontology_evolution`) opens a
`SEASON_YEAR_JOB_RETRY_WINDOW_DAYS`-day (5) retry window on a season/
year boundary but — unlike `_monthly_gate`, which correctly restricts
its own retry window to `"day_end"` ticks only, once per day — had no
such restriction: once open, the window returned True (and, on
failure, incremented `calls_dropped_backpressure`) on literally EVERY
tick for up to 5 days, for nine different jobs. Same bug class as
v1.34.81's nature triggers, just bounded to a fixed window instead of
open-ended, and spread across more jobs.

Fix: `_season_year_gate` now also requires `"day_end" in events`
before evaluating the retry window, matching `_monthly_gate`'s already
-correct shape. Costs nothing on the window's own OPENING tick — a
season/year boundary is itself always a day boundary (`SimClock.
advance` sets `season_end`/`year_end` and `day_end` on the same tick
by construction), so the first, most time-sensitive check is
unaffected; only the subsequent every-tick re-checks during the
window are now once-a-day instead.

Verified: a direct unit test against a real `SimulationEngine`/`World`
(opening tick with `day_end` present returns True; a later in-window
tick WITHOUT `day_end` now returns False, where it used to return
True; the next real `day_end` tick inside the window still retries
correctly); `pyflakes` clean; a 4000-tick LLM-disabled soak with clean
round-trip. Pure Python, no native module or persisted state touched.

## [1.34.81] — Fix: reactive nature triggers re-spamming backpressure drops every tick

Explicit user follow-up: "check that [pacing reachability] first, and do
whatever you can to fix the [backpressure] drop rate without reducing
simulation quality."

Confirmed the pacing mechanism (`LLM_PRESSURE_SLOWDOWN_START_RATIO`)
was reachable and firing correctly given the diagnostic's own numbers
— not the problem. The real problem, found by tracing where `calls_
dropped_backpressure` actually comes from: `_maybe_schedule_nature_
causal_reasoning`'s three triggers (predator/grazer extinction,
succession stall) are the only jobs in the codebase checked
UNCONDITIONALLY every single tick while their own anomaly persists —
every other LLM job is cadence-gated (month/season/year boundary) or
resolves via a graceful deterministic fallback the same tick
(`voice_dialogue`, the other candidate suspect, was checked and
confirmed to never drop — it degrades to fallback dialogue instead).
Cross-referencing the diagnostic's own `nature_pillar.world_model`
timestamps (this run's `nature_causal_reasoning` succeeded only 6
times total) against its `llm_backpressure_limit_effective` (3, from
a `llm_max_concurrent=1` deployment) shows the SAME still-unresolved
anomaly's backpressure check re-firing — and re-incrementing the drop
counter — on literally every tick for thousands of consecutive ticks,
not thousands of genuinely distinct attempts.

New `SimulationEngine._reactive_pillar_backpressured(pillar_name,
trigger_key)`: wraps the existing `_pillar_interpret_backpressured`
with a short per-trigger backoff (`REACTIVE_TRIGGER_BACKPRESSURE_
RETRY_TICKS=50`) — while backed off, returns "still pressured" WITHOUT
touching the counter or the LLM queue at all; once the window elapses,
one real check happens (and re-arms the backoff if still saturated).
The anomaly-detection itself (the cheap non-LLM state read) stays
fully unconditional every tick — only the expensive, countable
backpressure re-check is throttled — so this costs at most a
negligible (≤50-tick) delay before the eventual successful call
against anomaly windows already observed running thousands of ticks
long; nothing about WHAT gets scheduled, HOW OFTEN a genuine call
succeeds, or any narrative content changes. Wired at all three
triggers (`predator_extinction`/`grazer_extinction`/`succession_
stall`, each its own backoff clock via `trigger_key`).

Also checked, per the explicit request to move low-priority calls to
deterministic systems where sensible: no further clear candidate
found this pass. The other high-volume jobs in the diagnostic
(`cognition` 818, `voice_dialogue` 562, `record` 153, `musing` 214)
are each already core-cast/significance/novelty-gated and are
deliberately LLM-authored texture per this project's own explicit,
repeatedly-reaffirmed priority order (Emergence > Memory efficiency >
Performance, docs/CONSTITUTION.md) — several structurally similar
jobs were already converted to "deterministic decision + LLM
narration only" in the v1.3.35 batch; these four don't fit that
shape (there's no already-deterministic decision underneath them to
extract, the LLM call IS the content). Converting them further would
trade genuine emergence for a metric this pass's actual fix already
addresses more precisely — flagged as checked, not silently skipped.

Verified: a direct unit test of `_reactive_pillar_backpressured`
against a real `SimulationEngine` instance (forced-saturated backlog:
first check increments the counter once, ten immediate re-checks
during the backoff window increment it zero further times, a check
after the window elapses increments it exactly once more and can
succeed once pressure genuinely clears); `pyflakes` clean; a 4000-tick
LLM-disabled soak with a clean round-trip (no new persisted state —
the backoff dict lives on `SimulationEngine`, not `World`, same as
every sibling edge-trigger flag). Pure Python, no native module
touched.

## [1.34.80] — Fix: reactive pillar beliefs piling up as near-duplicate entries

Explicit user request: diagnose a real 40k-tick live run (with LLM,
`nemotron-4b-q5_k_m`, `hearthmind_version` reads `1.34.69` in its own
`training_recorder.dataset` — an older deployment, not this session's
in-progress work) and fix any real bugs found.

Real bug found: `nature_pillar.world_model` showed the SAME subject
("the vanished predator packs") re-hypothesized 5 separate times
across ticks 29334-36364, each a near-identical restatement, never
consolidating; `reflection_pillar.world_model` showed the SAME subject
("a change in whispering stone") with the SAME belief text
("false_memory: rustle near the road") appended as 9 separate entries
across ticks 5393-37582. Root cause: `_maybe_react_to_predator_
extinction`/`_maybe_react_to_grazer_extinction`/`_maybe_react_to_
succession_stall` (`nature_causal_reasoning`'s three reactive
triggers, v1.34.10/34/43) and the `consciousness` job's Reflection
mirror (v1.34.9) all call `Pillar.upsert_world_model(...)` with no
`revises_id` — `upsert_world_model` only revises in place when the
CALLER already knows which entry to revise; every other call site in
the codebase gets that from the LLM's own `revises` field, but these
four sites have no such field (their subject is a fixed string picked
by the trigger, not the model) and never looked up whether an entry
with that exact subject already existed, so every re-firing of the
same still-unresolved anomaly (ecology naturally flaps — packs go
locally extinct, recolonize, go extinct again) or the same repeated
consciousness intervention silently appended a fresh near-duplicate
instead of revising the pillar's one standing belief about it.

New `Pillar.find_world_model_entry(subject)` (`cognition/pillar.py`):
exact (case/whitespace-insensitive) subject match, most recent first —
deliberately NOT `disagrees_with`'s fuzzy substring/overlap match,
since these callers already hold their own subject string verbatim
and a loose match risks merging two genuinely different anomalies.
Wired at all four sites (`engine.py`): each now looks up any existing
entry with the same subject and passes its id as `revises_id`, so a
recurring anomaly updates ONE evolving belief (`nature_pillar`'s "the
vanished predator packs" now tracks the LATEST cause, not five stale
snapshots) instead of an ever-growing pile of near-copies. A genuinely
different anomaly (a different subject string) still appends a new
entry, unaffected.

No other clear code bug found in this pack: the very high `calls_
dropped_backpressure` (10022 vs. 2043 attempted) reflects this
deployment's own `llm_max_concurrent=1` override under a slow model,
not a defect — CLAUDE.md already documents this exact concurrency
constant's tuning history extensively; re-tuning it from one report
without a fresh live re-measurement would repeat a mistake this
project has explicitly corrected before (see `Config.llm_max_
concurrent`'s docstring). `village_pillar`/`humans_pillar`/`innovation_
pillar`'s world_model entries mixing content from both `whispering
stone` and its fissioned daughter `Stonehaven` is expected, not a bug —
the five pillars are genuinely world-scoped singletons, not per-
settlement, by design (see "The Pillar abstraction," v1.5.0).

Verified: direct unit tests of `find_world_model_entry`/`upsert_world_
model`'s revise-in-place behavior (same-subject revision, distinct-
subject still appends, case/whitespace-insensitive match, no-match
cases); `pyflakes` clean; a 4000-tick LLM-disabled engine soak with a
clean `World.to_dict`/`from_dict` round-trip (no persisted-shape
change — `world_model` entries already round-tripped; this only
changes how many accumulate). Pure Python, no native module touched,
so no native-soak run needed for this fix specifically (though the
same session's A5/A6 native soak below already ran clean on the
current tree).

## [1.34.79] — A5/A6: decay's native fast path, closing the item entirely

Explicit user instruction: "Do the native module change and ask me
when in doubt" — the one piece v1.34.78 explicitly flagged and did not
attempt: `Settlement.tick`'s decay loop has a native C++ fast path
(`_native_building_decay_tick`, modules 9-10 of the R6 port) that took
one flat scalar decay rate for the whole batch, so `material_repair_
factor`'s real-material-sensitivity trick (pure Python, agent-mediated
repair, zero parity risk) had no equivalent on the decay side without
either grouping buildings by material before calling into the native
function (awkward, loses the native path's whole-batch efficiency) or
a genuine native-module signature change. Ships the real signature
change, no ambiguity arose worth asking about.

`cpp/src/settlement_decay.cpp`'s `building_decay_tick` input tuple
gained a 5th field, `material_decay_factor` — multiplied directly into
the existing `hut_decay`/`civic_decay` scalar before the condition
subtraction. The factor itself is computed entirely in Python, once
per building, at `World.tick`'s call site (`world/state.py`) rather
than inside `settlement/buildings.py` — `world/materials.py` already
imports `BuildingKind` FROM `settlement/buildings.py`, so the reverse
import would be circular; `world/state.py` already imports both
modules cleanly, the same "compute where both dependencies already
meet" shape `nature_adaptation_bias`'s feed into `decay_disaster_
scars` established. New `world/materials.py`'s `material_decay_factor
(name)` mirrors `material_repair_factor`'s exact shape (`MATERIAL_
DECAY_FACTOR_BASE=0.5` + `Material.decay_rate * MATERIAL_DECAY_
FACTOR_DECAY_RATE_WEIGHT` (1.0)) but reads `Material.decay_rate`
instead of `workability` — a property tracked since A12 (v1.17.0) with
zero real consumer until now. Stone/ore/ceramic (`decay_rate` 0.05/
0.2/0.08) now weather at ~0.55-0.7x the old flat rate; wood/fiber
(0.5/0.7) at ~1.0-1.2x, wood staying close to its old tuned value since
it's the most common kind. `name=None`/unrecognized returns exactly
1.0, the old flat rate, unchanged.

`Settlement.tick` gained an optional `material_decay_factors: dict[
int, float] | None = None` param (keyed by `Building.id`), threaded
into both the native call site's now-5-tuple `inputs` list and the
pure-Python fallback loop (`building_decay *= material_decay_factors.
get(building.id, 1.0)` when provided) — `None` reproduces the exact
pre-A5/A6 flat rate on both paths, byte-for-byte. `scripts/verify_
native_soak.py`'s `_NATIVE_TOGGLES` already listed `(_buildings,
"_native_building_decay_tick")` from the original module-9 port — no
new toggle entry needed, the existing one now exercises the extended
signature directly. No new UI surfacing needed — v1.34.78's "Built of"
inspector repair-speed suffix already reads the same per-instance
material and now implicitly covers the decay-speed reading too (a
material that repairs fast/slow is the same one that decays slow/fast
by construction, so a second redundant line was judged unnecessary).

Verified: the native extension was rebuilt from the modified `.cpp`
source and confirmed to load and accept the new 5-tuple; direct
`material_decay_factor` unit checks across every registered material
confirming the expected stone/ore/ceramic-slower-than-wood/fiber
ordering; a production-path test through the real, native-backed
`Settlement.tick()` (fiber vs. stone buildings, 50 ticks, identical
weather/season) confirming genuinely differential decay plus a
byte-identical `None`-path regression check; a 4000-tick LLM-disabled
engine soak with a clean `World.to_dict`/`from_dict` round-trip (no
new persisted state — the factor dict is recomputed fresh every tick,
never stored); `scripts/verify_native_soak.py` (3 seeds x 3000 ticks)
confirming native and fallback produce byte-identical `World.to_dict()`
output at every tick — the load-bearing check for a native-module
signature change. **A5/A6 is now fully closed** — no flagged pieces
remain under either half of the item.

## [1.34.78] — A5/A6: per-instance Entity.properties, closing the item's other named half

Explicit user instruction: "Start A5/A6" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 3). The item names two halves: per-instance
`Entity.affordances` and per-instance `Entity.properties`. Direct code
inspection found the affordances half already genuinely closed —
`world/materials.py`'s `building_instance_affordances` (shipped
alongside A13's per-instance material conversion, v1.34.58) already
resolves a real per-INSTANCE material via `effective_material_name`
and derives boolean capability tags from it, wired live into
Innovation's discovery-combination query (`SimulationEngine`'s
`_maybe_schedule_ontology_proposal`, `present_tags`). This ships the
other half, which had zero real consumer: `Entity.properties` — a
material's raw NUMERIC properties (hardness/workability/durability/
etc.), as opposed to the boolean affordance tags derived from them.

Root gap found while surveying for a safe consumer: `Material.
workability`/`decay_rate` have existed since A12 (v1.17.0) and were
never read by anything — every building decayed and repaired at
identical flat rates regardless of whether it was wood, stone, metal,
or fiber, even though the property values needed to differentiate
them were sitting right there. Decay itself was deliberately left
alone — `Settlement.tick`'s decay loop has a native fast path
(`_native_building_decay_tick`, modules 9-10) that takes one shared
scalar decay rate for the whole batch; correctly per-instance-izing it
would mean either a real native-module signature change (a genuinely
bigger, riskier lift) or grouping buildings by material before calling
into the native function — both flagged as real follow-up, not
attempted this pass.

Repair, by contrast, is agent-mediated (`Population._maybe_repair`),
pure Python, and was never native-backed — zero parity risk. New
`world/materials.py`'s `material_repair_factor(name)`: a material's
`workability` scales `_maybe_repair`'s existing `REPAIR_WORK_PER_TICK`
rate — wood/fiber/clay (workability 0.75-0.9) repair meaningfully
faster than stone/ore/ceramic (0.1-0.25), matching the real intuition
that patching a wooden hut is quicker than re-laying stonework. Reads
`effective_material_name(building)` (A13's existing per-instance
resolution point), so a chemically-converted building's real new
material genuinely changes its own repair speed, not just its
affordance tags. A kind with no assigned material (SCHOOL/UNIVERSITY/
MARKET/LIBRARY) or an unrecognized name returns exactly 1.0 — the old
flat-rate behavior, byte-identical.

UI: the building click-inspector's existing "Built of" line (A13,
v1.34.58) gained a plain-language repair-speed suffix ("slow to
repair"/"repairs at an ordinary pace"/"quick to repair"), mirroring
the backend's factor buckets client-side same as `BUILDING_MATERIAL`
already does for the material name itself.

Verified: direct unit tests for `material_repair_factor` (ordering
across all eight materials, `None`/unrecognized-name no-op); a
production-path test through the real `Population._maybe_repair`
comparing a ceramic SHRINE against a fiber HATCHERY at identical
starting damage, confirming the fiber building genuinely repairs
faster; a 4000-tick LLM-disabled soak with clean round-trip (no new
persisted state — `material_repair_factor` is a pure read of already-
persisted `Building.material`); `scripts/verify_native_soak.py` (3
seeds x 3000 ticks) byte-identical — the native decay fast path itself
is untouched, only the pure-Python repair path changed; a live dev
server + Playwright pass confirming the inspector renders the new
repair-speed line correctly with no new console errors.

## [1.34.77] — A17: fitness-vs-truth axis for rumors + shared decay/compete step

Explicit user instruction: "A17", resolved via `AskUserQuestion` into
"both remaining pieces" (docs/ROADMAP-2026-07-REMAINING.md) — the two
items a prior audit (v1.34.59) found and explicitly flagged as needing
a user decision rather than an implementation judgment call, since
each carried a real risk the audit wasn't willing to take unilaterally.

**Fitness-vs-truth axis for rumors** ("false beliefs propagate if fit,
not suppressed for being false"). The blocking concern: a fitness
score needs a ground-truth value per rumor to demonstrate against,
which would cut against Phase G's standing principle that belief never
has to reconcile with objective reality. Resolved by never measuring
against objective reality at all — new `world/memetics.py`'s
`rumor_truth_score` measures textual fidelity to what was ORIGINALLY
SAID (the rumor as first heard), never against the state of the world;
`rumor_fitness` is an independent closed-vocabulary "how dramatic does
this read" heuristic. Wired at `SimulationEngine._maybe_interpret_
rumor`'s `apply()` — after InterpretRumor() produces a listener's own
distorted retelling, `fitness`/`truth_score` are computed against it.
Real consequence: new `Population._apply_rumor_retelling_fitness`
polarizes the RETELLER's own existing opinion of whoever their
retelling names, scaled by `fitness` alone — `truth_score` is tracked
(new `SimulationEngine._rumor_retellings_recent`, capped, transient,
dev-console/`full_diagnostics()` only) but deliberately plays no role
in the nudge, so a dramatic-but-distorted retelling entrenches opinion
exactly as readily as a faithful-but-dull one would. A fully-neutral
opinion is left untouched rather than given an invented direction.

**Shared decay/compete step** (the other named A17 gap). The prior
audit found two candidate sites and flagged both: `Settlement.lexicon`
because its only reader was confirmed dead code, `recent_topics`/
`top_topics()` because touching it risked destabilizing v0.87.35's
live-tuned topic-diversity mechanism without a fresh live-diagnostic
read (unavailable in this environment). Resolved by wiring the safe
direction only. New `world/memetics.py`'s `find_near_duplicate`
("compete": a near-restatement of something already tracked collapses
to the established phrasing) and `prune_aged_entries` ("decay": an
age-based prune distinct from a flat count cap) are the shared
primitives. `SettlementCulture.record_topic` now calls `find_near_
duplicate` before appending — a topic phrased two ways no longer
dilutes its own frequency count, which if anything makes the existing
exact-string dominant-topic gate in `_apply_pending_dialogue_results`
MORE accurate, reasoned through without touching any of v0.87.35's
actual tuned constants (novelty thresholds, category weights, pick
counts). `Settlement.lexicon`'s coinage site gets both: `find_near_
duplicate` on a proposed coinage's MEANING (a near-synonymous idea
competes with, rather than duplicates, an already-coined term,
alongside the existing exact-TERM duplicate check) and `prune_aged_
entries` as a genuine age-based decay (`LEXICON_MAX_AGE_TICKS`,
~3 years) — both riding the lexicon's own existing quarterly append
call site, zero new cadence.

Verified: direct unit tests for all four new `world/memetics.py`
functions (including an explicit fitness-vs-truth independence
demonstration — a distorted-but-dramatic retelling scoring HIGH
fitness/LOW truth, a faithful-but-dull one scoring the reverse);
production-path tests for `SettlementCulture.record_topic`'s compete
step and `Population._apply_rumor_retelling_fitness` (including the
neutral-opinion no-op case) against real `Agent`/`SettlementCulture`
instances; a full end-to-end test driving the real `_maybe_interpret_
rumor` -> `_schedule_llm_job` -> `apply()` pipeline with a fake LLM
adapter, confirming the retelling, fitness/truth computation, opinion
polarization, and diagnostics ring all fire through the actual
production scheduling path; a 4000-tick LLM-disabled soak with clean
round-trip (no new persisted state); `scripts/verify_native_soak.py`
(3 seeds x 3000 ticks) byte-identical — pure Python, no native module
touched.

## [1.34.76] — M1/M9: field boundaries drawn on the map

Explicit user instruction: "Build M1/M9 and ask questions if stuck"
(docs/ROADMAP-2026-07-REMAINING.md's Tier 1.5). Closes Tier 1.5 "The
Living Map" entirely — "field boundaries" was the one residual named
example left unbuilt since v1.34.50, flagged both times as "a
genuinely larger UI-redesign lift, not attempted this pass." Turned
out not to need one: a real, self-contained frontend-only slice.

Root gap: `latest.farms` was already real per-tile data reaching the
client every broadcast, but each farm tile was drawn as an
individually-tinted square — a cluster of farmed tiles never read as
an actual FIELD, a bounded plot a farmer works, the way a building's
own outline already reads as a real structure.

New `app.js` `drawFieldBoundaries(farms)`: traces a thin hedgerow-
style line around the outer edge of every contiguous cluster of farm
tiles — for each farmed tile, any of its 4 neighbors NOT also farmed
gets a boundary segment on the shared edge. Same "one segment per
crossing" technique `drawFieldContour` already established for the
moisture wetland threshold isoline (v1.34.32), just over a binary
membership set instead of an interpolated value, so no new drawing
primitive was needed. Zero new backend state, zero new payload field —
pure client-side rendering over data already flowing. Drawn on the
main map canvas immediately after the farm fill loop, always on (not
a togglable overlay mode), matching the standing Observatory UI
discipline that ordinary continuous state belongs on the map itself,
not gated behind a mode switch.

No `AskUserQuestion` was needed — the roadmap's own prior entries
already scoped the item precisely enough ("field boundaries drawn on
the map," M9's own named example list) that the smallest honest
reading (a real boundary line around real farm-tile clusters, reusing
an already-proven contour-tracing technique) was unambiguous.

Verified: `node --check` clean; a live dev server + Playwright pass —
zoomed screenshot of a real isolated single-tile farm plot confirms a
distinct thin brown boundary line rendering around the farm fill,
visually separate from the tile's own inset color fill, with no new
console errors. Pure frontend change, no Python file touched — no
native soak needed this pass.

## [1.34.75] — A2's first `reaction_diffuse` consumer + A1's mining_scars/disaster_scars/climate-grid FieldGrid migration

Explicit user instruction: "Build A2 and A1 migrate mining_scars/
disaster_scars/the 3x3 climate grid onto FieldGrid" (docs/ROADMAP-
2026-07-REMAINING.md).

**A2** — `world/ca_operators.py`'s `reaction_diffuse` (strictly mass-
conserving two-grid exchange) had zero real consumers since it shipped
at v1.14.0, unlike `diffuse` (many) and `cellular_step` (one). Ships
its first: `moisture <-> snowpack`, the one genuinely honest pairing
in this codebase — literally the same water in liquid vs. frozen form,
reusing the already-tracked `HydrologyField.moisture` full-resolution
grid as one half. New `HydrologyField.snowpack` (same full-tile-
resolution shape as `moisture`/`groundwater`, zero at genesis — worlds
always start in spring, so "no accumulated snow yet" is the honest
default, not a neutral midpoint). New weekly `hydrology_field.
tick_snowpack`: below `SNOWPACK_FREEZE_TEMP_C` moisture converts to
snowpack at `SNOWPACK_FREEZE_RATE`; above it, snowpack melts back to
moisture at the faster `SNOWPACK_MELT_RATE` — `reaction_diffuse`'s
`rate_a_to_b`/`rate_b_to_a` are simply zeroed in the direction not
currently active, so the exchange is one-directional per week but the
underlying primitive stays genuinely bidirectional. Water-biome tiles
are pinned to full moisture / zero snowpack after the exchange, same
discipline `tick_hydrology` already holds.

Real consumer: `world/wildlife.py`'s `WildlifeGrid.tick()` gained a
`snowpack` param — `SNOWPACK_REPRODUCE_DAMPENING_MAX=0.3` dampens a
GRAZER herd's reproduce chance under deep accumulated snow cover
(direct per-tile lookup via new `_full_grid_value`, distinct from
every other field consumer wired into this function so far, which all
read the coarse 3x3 `FieldGrid` via `_field_region_value` — snowpack
matches `terrain`'s full resolution, not the coarse region grid).
"Real winter forage scarcity," stacking with (not replacing) the
existing nutrients/hardiness/season terms in the same formula. UI: the
existing "Soil moisture" stat tile gained a conditional snowpack
percentage suffix, shown only once real snow has accumulated.

**A1's mining_scars/disaster_scars/climate-grid migration** — the item
explicitly deferred at v1.34.71/72 (re-asked, unanswered), now
directly instructed. Scoped as "give each store a genuine coarse
REGION-scale `FieldGrid` companion reading, not a literal replacement"
— `World.mining_scars`/`disaster_scars` (sparse per-TILE dicts) and
`World.weather_regions` (already region-scale) all remain the source
of truth for their existing tile-precise or full-`WeatherState`
consumers; nothing about them changed. `mining_scars` already had a
partial region-aggregate reading via `step_pollution`; this closes the
two genuinely missing halves.

Two new `FieldGrid` fields (14th/15th): `hazard` (`step_hazard`,
`World.disaster_scars` summed per region, spread via `diffuse`) and
`storminess` (`step_storminess`, `World.weather_regions`'
`precipitation`/`wind` — the "3x3 climate grid" the roadmap's own note
names — weighted-combined per region, spread via `diffuse`). Two new,
non-overlapping real consumers, chosen for variety rather than piling
onto the already-heavily-used `_maybe_welcome_migrant`:
`SimulationEngine._choose_fission_site` now avoids a region reading
`hazard >= HAZARD_FISSION_AVOID_THRESHOLD` (0.5) when a less
disaster-scarred alternative exists — "don't rebuild where the last
settlement kept burning down" — applied after the existing density/
scent/fertility filters, never a hard block. `_maybe_schedule_caravan`
gained `STORMINESS_CARAVAN_CHANCE_DAMPENING=0.4`, the real negative
counterpart to `traffic`'s existing positive pull on the same `chance`
value — "traders avoid storms."

**Bug fix found while wiring this batch**: one of the two `set_
terrain(...)` call sites in `simulation/engine.py` (the `week_end`
periodic-resync path) had been missing `beauty=world.fields.ensure_
field("beauty")` entirely since v1.34.74 shipped — a real omission
that batch's own verification didn't catch. Practical consequence: the
`beauty` map overlay only ever refreshed on `TERRAIN_CHANGING_
CATEGORIES` events, never on the weekly resync every sibling
continuous field relies on to stay visually fresh. Fixed in the same
edit that added `hazard=`/`storminess=` to that call site.

UI: `hazard`/`storminess` added as the 16th/17th "🗺️ fields" overlay
modes, each with its own 3-stop color ramp (hazard: neutral grey-green
through scorched umber to blackened char-red, distinct from `scent`'s
amber-toned danger ramp since this is scar/burn damage, not a live
predator threat; storminess: pale sky-blue through slate-grey to dark
thunderhead indigo, a cool "weather" hue family distinct from `heat`'s
warm ramp) and matching legend min/max labels.

Verified: direct unit tests (`tick_snowpack`'s freeze/thaw exchange
via a forced-temperature scenario; `step_hazard`/`step_storminess`'
region-aggregation math); a production-path test through the real
`World.tick()` with `state.compute_weather` monkeypatched to force
sustained freezing weather, confirming organic snowpack formation
through the actual tick path (not reachable by simply setting `weather.
temperature_c`, since `World.tick()` recomputes weather at the top of
every tick) plus a clean round-trip; a 4000-tick LLM-disabled soak
with clean round-trip; `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical — pure Python, no native module touched; a live
dev server + Playwright pass confirming both new overlay modes render
with correct gradients/legends/hotspot markers and no new console
errors (screenshots confirmed visually — a stray `textContent` read of
the hidden per-mode threshold line during scripted verification was a
test-tooling artifact, not a real rendering bug, confirmed via direct
screenshot inspection).

## [1.34.74] — A1: beauty field (13th, closes A1 entirely)

Explicit user instruction: "Ask the beauty phase of A1 and finish it."
Asked via `AskUserQuestion` for a real design decision on `beauty`'s
mechanical meaning (the only genuinely open item under A1 as of
v1.34.73), offering three options: a deterministic composite of
already-real state (fertility/pollution/scars/shrines), skip entirely,
or a genuinely new per-agent subjective-vote mechanic. **Explicit user
answer: "New subjective agent-vote signal."** This ships that answer —
the one `FieldGrid` field in the whole system that is NOT a live
re-read of already-real deterministic state.

New `world/aesthetics.py`: `compute_aesthetic_appraisal` — a pure
function scoring the tile a voting agent stands on (0..1) from real
environmental cues (water-adjacency, a scenic biome underfoot,
neighborhood biome variety, mining/disaster scar penalties), then
nudged by the voting agent's own `TRAIT_OPENNESS` — the genuinely
SUBJECTIVE half, the same real trait that already shapes how readily a
settlement welcomes strangers (`TRAIT_OPENNESS_MIGRANT_WELCOME_
INFLUENCE`). `tick_aesthetic_votes` gives every living agent a cheap
`BEAUTY_APPRAISAL_CHANCE_PER_TICK=0.02` roll each tick; an agent who
votes folds their appraisal into `World.aesthetic_appraisal`, a new
persistent 3x3 per-region exponential moving average — genuinely
different from every sibling field's "raw already-real state, re-read
fresh each tick" shape: this is a running belief that accumulates and
drifts as opinion shifts, seeded at a neutral 0.5 (not "absence means
zero," since an unvoted region has no opinion yet, not an objectively
ugly one). `FieldGrid.step_beauty` spreads it via `ca_operators.
diffuse`, the same spatial-bleed treatment every other field gets, on
top of (not instead of) the accumulator's own separate temporal
smoothing.

Real consumer, reusing the proven `_maybe_welcome_migrant` shape one
more time: `MIGRANT_BEAUTY_PULL=0.2`, a fourth POSITIVE region-field
pull (alongside `ownership`/`cultural_influence`) — "word travels that
a place is beautiful." UI: 13th and final "🗺️ fields" overlay mode
("beauty (villagers' own opinion)"), own coral/rose-gold color ramp
distinct from every warning/organic/roots hue family the other twelve
modes use, since this is the one field literally measuring collective
affection for a place.

**This closes A1 entirely** — all thirteen named fields (twelve
originally-scoped plus `beauty`) are now real, with real consumers, and
real map overlays. No open items remain under this roadmap entry.

Verified: 5 direct unit tests (scenic-vs-plain scoring, scar penalty,
openness trait shift, many-vote convergence toward the voted score,
diffusion into the field), a production-path test through the real
`World.tick()` over 300 ticks confirming organic formation, a clean
`to_dict`/`from_dict` round-trip, AND a legacy-backfill test (a
snapshot missing the new `aesthetic_appraisal` key loads back to the
neutral 0.5 default rather than crashing), a 4000-tick LLM-disabled
soak with clean round-trip, `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical — pure Python, no native module touched —
and a live dev server + Playwright pass confirming the overlay cycles
to "beauty" with a matching legend and no new console errors (the same
pre-existing unrelated `favicon.ico` 404 as every prior pass, confirmed
via direct `curl`).

## [1.34.73] — A1: fertility field (12th, closes the field-count checklist)

Explicit user instruction: "Continue A1." Ships the last named field
this doc's own checklist ever tracked, `fertility` — a genuine
`FieldGrid` region aggregate, distinct from `FarmGrid.soil_fertility`'s
existing dense per-farmed-tile dict and from `world/spatial_memory.py`'s
`location_character` (which reads that same dict for ONE tile's flavor
text). `FieldGrid.step_fertility` averages `soil_fertility` per region
(same already-bounded-average shape `step_scarcity` established, no
`_normalize_peak` needed since the source is already 0..1), spread via
`ca_operators.diffuse`. Real consumer, deliberately NOT a duplicate of
`location_character`'s tile-level read: `SimulationEngine._choose_
fission_site` gains a third region-field filter, `FERTILITY_FISSION_
PREFER_THRESHOLD=0.4` — a candidate site in a region already reading as
good farmland is preferred over one that isn't, when a qualifying
candidate exists (never a hard block, applied last after the existing
density/scent filters). UI: 12th "🗺️ fields" overlay mode ("regional
fertility"), own tan-to-gold-to-green color ramp distinct from the
existing tile-level "soil fertility" mode's own ramp.

Only `beauty` and the mining_scars/disaster_scars/climate-grid
`FieldGrid` migration remain open under A1 — both per the same
unanswered-`AskUserQuestion` defaults recorded at v1.34.72 (skip
`beauty`, leave the migration deferred); neither was re-asked this
pass since nothing changed about either since the last answer.

Verified: 2 direct unit tests for `step_fertility` (region with farmed
tiles reads higher than a bare one; empty input stays all-zero), a
production-path test through the real `World.tick()` with forced
`soil_fertility` confirming organic formation plus a clean round-trip,
a 30-trial deterministic consumer test (forced fertility field, every
one of 30 `_choose_fission_site` draws landed in the fertile region), a
4000-tick LLM-disabled soak with clean round-trip, `scripts/verify_
native_soak.py` (2 seeds x 800 ticks) byte-identical, and a live dev
server + Playwright pass confirming the overlay cycles to "regional
fertility" with a matching legend and no new console errors (one
pre-existing unrelated `favicon.ico` 404 confirmed via direct `curl`,
same as prior passes).

## [1.34.72] — A1: cultural_influence field (11th) + correction of v1.34.71's own scope note

Explicit user instruction: "Continue A1 and ask questions if your are
stuck." Asked via `AskUserQuestion` whether to design a mechanical
meaning for `beauty` and whether to attempt the mining_scars/disaster_
scars/climate-grid `FieldGrid` migration flagged open at v1.34.71 —
**both questions went unanswered**. Proceeded on the stated
recommended defaults: `beauty` stays unbuilt (skipped, not attempted),
the store migration stays deferred. Neither is a user-confirmed
decision; re-raise both on a future pass rather than treating this as
settled.

While investigating those two, found that v1.34.71's own claim about
`cultural-influence` — "no real data source anywhere in this codebase
without inventing a new subjective-scoring mechanic from scratch" —
was wrong. `world/ontology.py`'s `InventedConcept.adopter_ids: set[int]`
is a real, already-tracked, already-capped set of agent IDs per
invented concept (any origin category — technology, custom, law,
ecological relationship). This correction supersedes that specific
claim in v1.34.71's CHANGELOG/CLAUDE.md entries below; the rest of
that entry stands.

Shipped the field for real. `FieldGrid.step_cultural_influence`
(`world/fields.py`): every living agent who has adopted at least one
invented concept counts once toward their current tile's region,
normalized against the most culturally active region, spread via
`ca_operators.diffuse` — same "live census, not an accumulating
quantity" shape `step_population_density` established (an agent who
stops adopting, or dies, simply stops being counted; no new tracked
state). `World.tick()` (`world/state.py`) computes the union of
`adopter_ids` across `World.invented_concepts` each tick and calls it
with living agents' positions. Real consumer:
`Population._maybe_welcome_migrant` gains a fifth optional region-field
term, `region_cultural_influence` (`MIGRANT_CULTURAL_PULL=0.25`) — a
third POSITIVE pull alongside `ownership`/`heat`'s siblings (density/
scarcity/heat all only ever dampen), "word travels that a place has
real ideas." UI: 11th "🗺️ fields" overlay mode ("cultural influence"),
own violet/lavender color ramp distinct from `ownership`'s warm-gold
"roots" ramp — this is intellectual/cultural presence, not physical
settledness.

Verified: 2 direct unit tests for `step_cultural_influence` (region
with more adopters peaks vs. its neighbors; empty adopter set stays
all-zero), a production-path test through the real `World.tick()` with
forced adopters confirming organic formation plus a clean `to_dict`/
`from_dict` round-trip, a 4000-tick LLM-disabled soak with clean
round-trip (field stays legitimately zero — no invented concepts form
organically with LLM disabled over that horizon; the forced-adopter
test above already proves the formation path), `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical — pure Python, no native
module touched — and a live dev server + Playwright pass confirming
the overlay cycles to "cultural influence" with a matching legend
("no adopters" -> "cultural hub") and zero console errors.

Honest accounting, same discipline as v1.34.71: this still does not
close A1. `fertility`-as-a-`FieldGrid`-aggregate and `beauty` remain
unbuilt (`beauty`'s AskUserQuestion went unanswered, defaulted to
skip); migrating `mining_scars`/`disaster_scars`/the climate grid onto
`FieldGrid` remains unbuilt (same unanswered-question default: leave
deferred). Real field count is now 11.

## [1.34.71] — A1: three more fields (heat/nutrients/scent) + honest scope note

Explicit user instruction: "Finish building A1 this turn." Ships three
more `FieldGrid` fields with real consumers in one batch, bringing the
real-field count to ten. **Does not literally close A1** — see the
honest accounting at the end of this entry; three named fields and a
separate store-migration item remain open, each with a concrete reason
rather than silently dropped.

`world/fields.py` gains:
- `step_heat`: sourced from `World.weather_regions`' already-real
  per-region `WeatherState.temperature_c` (no new tracked state,
  `WEATHER_REGION_GRID` already equals `FIELD_GRID_SIZE`), normalized
  against `HEAT_COLD_C`/`HEAT_WARM_C` — deliberately mirrored floats
  matching `disasters.FROST_TEMP_THRESHOLD`/`HEATWAVE_BUILD_TEMP`
  rather than inventing new thresholds. Consumer: `Population._maybe_
  welcome_migrant`'s new `region_heat` term (`MIGRANT_HEAT_DAMPENING
  =0.25`) — a scorching region draws newcomers a bit less readily,
  same bounded shape as the density/scarcity terms.
- `step_nutrients`: sums `World.resources`' standing FOOD-node amounts
  per region (already-real wild-food state). Consumer: `WildlifeGrid`'s
  grazer `reproduce_chance` gains a bonus in nutrient-rich regions
  (`NUTRIENTS_REPRODUCE_BONUS_MAX=0.4`) — a genuine positive signal
  from raw forage abundance, distinct from the existing predator-
  pressure penalty term. Computed in Python before reaching the native
  `_native_grazer_tick_step` fast path, same zero-parity-risk shape
  the module's own docstring already established for `reproduce_
  chance`.
- `step_scent`: sums live predator-pack sizes per region (already-real
  `WildlifeGrid.herds` state). Consumer: `SimulationEngine._choose_
  fission_site` prefers a low-scent region when an alternative exists
  (`SCENT_FISSION_AVOID_THRESHOLD=0.6`), same "never a hard block"
  shape its existing `population_density` filter already uses — a
  region-scale danger reading distinct from the existing TILE-level
  predator avoidance in `Population._step_toward`/`_maybe_move`.

UI: three more "🗺️ fields" modes (heat/wild forage/predator scent, 13
total now), each with its own color ramp and legend.

**Honest accounting against "finish A1" — what's still open and why:**
- **`fertility` (as a genuine FieldGrid region aggregate, distinct
  from `FarmGrid.soil_fertility`'s existing dense per-farmed-tile
  dict), `cultural-influence`, `beauty`** remain unbuilt. The first
  would largely duplicate an axis `location_character` already reads
  directly from `FarmGrid`; the latter two have no real data source
  anywhere in this codebase to read from without inventing a wholly
  new subjective-scoring mechanic from scratch — a genuinely separate,
  larger design task, not a same-shape slice like this batch's three.
- **Migrating `mining_scars`/`disaster_scars`/the 3x3 climate grid
  onto `FieldGrid` properly** remains unbuilt — a real refactor of
  three already-tuned, already-consumed stores (mining/disaster scars
  feed `location_character`/site-scoring, the climate grid feeds
  `weather_at`) touching many call sites for no behavior change,
  correctly judged too large and too risky to fold into this batch
  alongside three new field slices with their own verification needs.

Verified: unit tests for all three `step_*` methods (bounds,
diffusion, empty-input degrade), a deterministic-formula check plus a
production-path smoke test for the heat migrant term, a 6000-trial
production-path test through the real `WildlifeGrid.tick` confirming
the nutrients reproduce bonus, a 200-trial production-path test
through the real `SimulationEngine._choose_fission_site` confirming a
forced-dangerous region draws zero fission sites while every other
region remains freely chosen, a 4000-tick LLM-disabled engine soak
with all three fields forming organically and a clean round-trip,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical,
and a live dev server + Playwright pass confirming all three new
overlay modes render with matching legends.

## [1.34.70] — A1: sixth `FieldGrid` field, `noise` (Tier 1)

Explicit user instruction: "Tier 1 A1 and Tick off completed items."
Ships Tier 1's sixth `FieldGrid` field, `noise` — deliberately NOT
sourced from any new tracked state, genuinely composite: `world/
fields.py`'s `FieldGrid.step_noise` is the mean of two fields this
class already computes every tick (`population_density`/`traffic`,
both already 0..1), then spread via `ca_operators.diffuse` same as
every other field here.

Real consumer: `world/wildlife.py`'s `WildlifeGrid._maybe_recolonize`
(the sole path back from local wildlife extinction) used to pick its
recolonization site by flat uniform choice among every eligible
biome tile on the map — it now weights that draw by `noise` via a new
`_choose_spot` helper (`RECOLONIZE_NOISE_DAMPENING=0.6`, floored so a
region is never fully excluded, falling back to uniform `rng.choice`
if every candidate somehow lands at zero weight): "wildlife resettles
the quiet corners of the map first, not the busy ones," a real
ecological consequence neither source field had on its own.
`noise=None` (the default) reproduces the exact pre-this-feature
uniform-choice behavior. New `_field_region_value` helper mirrors
`FieldGrid.get_at`/`region_of`'s bucketing math without importing
`FieldGrid` itself (wildlife.py has no other reason to depend on it).
Read one tick stale, same as every other `World.fields` consumer
(`WildlifeGrid.tick` runs before this same tick's `fields.step_*`
calls).

UI: 10th "🗺️ fields" mode ("disturbance"), own violet-to-magenta color
ramp distinct from every warning-red mode and from `traffic`'s own
blue-cyan ramp (noise is downstream of traffic, not a restatement).

Verified: 2 direct unit tests for `step_noise` (empty-input degrades
to all-zero; composite genuinely peaks where its two source fields
peak), a 3000-trial production-path test through the real
`_maybe_recolonize` confirming a quiet region draws markedly more
recolonization arrivals than a noisy one, a smoke test confirming
`noise=None` still runs the old uniform-choice path unchanged, a
4000-tick LLM-disabled engine soak with clean round-trip,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
(pure Python, no native module touched — `_maybe_recolonize` was
never natively ported, only the per-tick grazer step was), and a live
dev server + Playwright pass confirming the new overlay mode cycles
correctly with a matching "quiet -> disturbed" legend.

## [1.34.69] — M1/M9: labeled environmental stress reading (Tier 1.5)

Explicit user instruction: "Continue with roadmap." Ships the one
residual named example Tier 1.5's own M1/M9 entry left open since
v1.34.51: "a labeled 'environmental stress'/degradation reading"
(docs/VISION-2026-07-24-LIVINGMAP.md's M7: "pollution/degradation ->
environmental stress... closest existing analog is the scar dicts,
just not labeled or overlaid as one").

`world/spatial_memory.py` gains `ENVIRONMENTAL_STRESS_AXES` (`mining`,
`disaster`, `pollution`, `fertility` — the subset of `location_
character`'s existing twelve axes that represents genuine HARM to the
land, not just accumulated history) and `compute_environmental_
stress`/`environmental_stress_label`: the mean of whichever stress axes
a tile actually has (`None` when a tile shows no degradation at all,
same "absence means neutral" discipline every other axis here holds),
banded into three plain-language readings. Pure read-side unification
over already-real state — no new tracked data.

UI: the bare-tile click inspector gains three new sections. Two close
a real pre-existing gap (mining/disaster scars were only ever visible
as a map color and an aggregate stat tile, never per-tile — unlike
ruin/road/migration/dry-lakebed scars, which already had inspector
lines). The third is the composite "Environmental stress" reading
itself, shown only past real degradation. `app.js`'s new `fieldRegion
Value` helper mirrors `FieldGrid.get_at`/`region_of`'s exact bucketing
math client-side (same intentional formula mirror as `MIN_LIFESPAN_
TICKS` already established) so the composite can read the region-level
`pollution` field for the specific tile clicked. Field boundaries (the
other, larger M1/M9 ask) remain open — a genuinely bigger UI-redesign
lift, not attempted this pass.

Verified: 5 direct unit tests for `compute_environmental_stress`/
`environmental_stress_label` (no-degradation, single-axis, multi-axis
averaging excluding non-degrading axes, band boundaries, a production-
path case through the real `location_character_from_dicts`); a live
dev server + Playwright pass forcing a mining+disaster+pollution+
depleted-soil tile and confirming all three new inspector sections
render correctly, plus a regression check on a pristine tile showing
none of them (the pristine check also incidentally confirmed `field
RegionValue`'s bucketing matches the backend exactly — an initially
too-close comparison tile fell in the SAME field-grid region as the
forced tile, exposing the correct behavior rather than a bug); a
4000-tick LLM-disabled engine soak with clean round-trip; `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical — pure
Python/JS, no native module touched.

## [1.34.68] — A2: `cellular_step`'s first real consumer (Tier 1)

Explicit user instruction: "Continue with roadmap." Shipped `world/
disasters.py`'s `compute_forest_contiguity` — `ca_operators.
cellular_step`'s first real consumer (`diffuse` has five, `reaction_
diffuse` still has none).

`_forest_contiguity_rule(own, neighbors)` scores a forest tile 1x (an
isolated stand) up to 2x (`WILDFIRE_CONTIGUITY_WEIGHT=1.0`, fully
boxed in by forest neighbors) by local forest density; a non-forest
tile always scores exactly 0. `tick_wildfire`'s weekly ignition roll
used to pick its ignition tile by flat uniform choice among every
forest tile on the map — it now weights the draw by this score
(`rng.choices`, falling back to the old uniform `randrange` only if
every candidate somehow scores 0), so a dense, continuous forest
cluster is genuinely more likely to be where the next wildfire starts
than an isolated single tree, the way a real fire actually needs
continuous fuel to catch. Deliberately scoped to WHICH tile ignites,
never WHETHER or HOW OFTEN — `WILDFIRE_CHANCE_PER_WEEK` and the
existing temperament/heatwave/`chance_multiplier` terms are untouched,
and the native-backed spread-roll/frontier mechanic once a fire is
already burning is untouched too (the roadmap's own note: forcing this
onto `tick_wildfire`'s sparse-tile-set roll-batch mechanic would be too
large a rewrite for what this item asks — this only reweights the
existing uniform ignition-site pick, a genuinely small, safe surface).

Verified: a direct unit test of `compute_forest_contiguity` (center of
a forest cross scores highest, an isolated single stand scores exactly
1.0, an all-grassland grid scores all-zero); a 2000-trial production-
path test driving the real `tick_wildfire` against a terrain with one
dense forest cluster and one isolated forest tile, forcing ignition
every trial (`chance_multiplier=1e6`), confirming the cluster's center
tile ignites markedly more often than the isolated tile; a 4000-tick
LLM-disabled engine soak with clean round-trip; `scripts/verify_
native_soak.py` (2 seeds x 800 ticks) byte-identical — pure Python, no
native module touched, and this module isn't native-ported for the
ignition-site pick either way, so no native/fallback parity risk.
`reaction_diffuse` remains the one primitive still without a real
consumer.

## [1.34.67] — A1/A2: fifth continuous field, `ownership` (Tier 1)

Explicit user instruction: "Continue with roadmap." Shipped Tier 1's
next `FieldGrid` field + `ca_operators.diffuse` consumer, `ownership`
— joining `population_density`/`disease_pressure`/`pollution`/
`traffic`.

`world/fields.py`'s `FieldGrid.step_ownership` sources from `World.
ownership_history` (A19, v1.34.55 — an already-real, permanent,
non-decaying per-tile count of how many times a HUT has passed to a
living heir), summed per region, normalized against the busiest
region, then spread via `ca_operators.diffuse` — same "re-read
already-real slow-changing state" shape `traffic`/`pollution`
established, no new tracked state invented.

Real consumer: `Population._maybe_welcome_migrant` gained a new
`region_ownership` parameter and `MIGRANT_OWNERSHIP_PULL=0.3` — a
region with deep inheritance history draws up to 30% MORE migrants at
its peak reading. This is the first genuinely POSITIVE region-field
pull in that function; `region_population_density`/`region_scarcity`
both only ever dampen. The framing is the plausible inverse of
scarcity's own docstring ("word travels that a place is struggling"):
word also travels that a place has real roots.

UI: 7th "🗺️ fields" overlay mode (labeled "settledness" — the plain-
language framing a player would actually ask, "where has this village
put down roots"), own color ramp (pale frontier grey-tan through
wood-brown to a heritage gold), legend entry, all wired through the
existing generic field-overlay/legend machinery — no new frontend
plumbing needed beyond the mode's own entries.

Also corrected a stale roadmap note: A12's checklist text still said
per-instance `Entity.material` was unbuilt ("class-level... not per
physical instance") after A13's chemistry reactor (v1.34.58) had
already shipped exactly that for buildings, as a side effect of that
pass. Generalizing beyond buildings (e.g. `Vehicle.material`) is
genuinely still open but was NOT attempted here — audited first, no
real consumer mechanism exists for it yet, and inventing one purely to
fill the slot would be an unmotivated addition.

Verified: 3 direct unit tests (`step_ownership` region aggregation/
normalization, empty-history no-op, `get_at` region resolution); a
deterministic threshold-crossing test of the migrant consumer using a
`random.Random` subclass whose first `.random()` call is fixed (so the
real chance formula's exact boundary is tested without RNG sampling
noise, real `.shuffle()`/`.randrange()` intact for the rest of the
call); 3 production-path tests through the real `World.tick()`/
`to_dict()`/`from_dict()` path; pyflakes clean; 4,000-tick LLM-disabled
soak with clean round-trip; `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical; a live dev server + Playwright pass
confirming the new overlay mode cycles correctly with a matching
legend and no new console errors (one pre-existing unrelated
`favicon.ico` 404 confirmed present independently via `curl`, not
caused by this change).

## [1.34.66] — B8 reinforce/reinterpret (Tier 3 item 24)

Explicit user instruction: "Continue with open items in roadmap." Shipped
Tier 3 item 24 — B8's own named remaining gap: `Pillar.consolidate()`
(B8, shipped earlier) folds/forgets old memory notes but nothing ever
strengthened or revised one, so a memory the pillar kept returning to
had no advantage over one noted once and never touched again.

`cognition/pillar.py`'s `Pillar` gains a new parallel `memory_access:
list[int]`, index-matched to `memory`, defaulting to 0 and legacy-
backfilled on load for snapshots saved before this change.
`remember()` now checks a new note against its `MEMORY_REINFORCE_SCAN`
(8) most recent notes via the same `word_overlap` Jaccard primitive
`disagrees_with` (B4) already established:

- Near-restatement (`>= MEMORY_REINFORCE_OVERLAP`, 0.55) — REINFORCE:
  bump the existing note's access count, no duplicate appended.
- Related but distinct (`>= MEMORY_REINTERPRET_OVERLAP`, 0.35) —
  REINTERPRET: replace the old note's text with the new one, also
  bumping access.
- Otherwise: append as a genuinely new, distinct memory, unchanged
  from before.

`consolidate()` is now access-count-aware: it folds the `MEMORY_
CONSOLIDATE_BATCH` LEAST-reinforced notes first (ties broken oldest-
first) instead of blindly the oldest positions — a note the pillar
keeps returning to now genuinely resists being folded away, the
"preserving identity" language B8's own spec text uses. The resulting
digest inherits the highest access count among the notes it folded,
so it isn't immediately the next thing consolidated either.

One shared method on `Pillar` means this reaches all five pillars
(Village/Humans/Innovation/Nature/Reflection) at once — not five
separate implementations, same as `consolidate()` itself originally.

`MEMORY_REINTERPRET_OVERLAP`'s value (0.35) was picked empirically,
not guessed: `word_overlap` is deliberately not stopword-filtered (a
documented tradeoff shared with `disagrees_with`), so two genuinely
unrelated short sentences can still cross 0.2-0.3 purely on shared
"a"/"the"/"was"/"to" — confirmed by running a batch of deliberately
unrelated notes through the actual function (max observed overlap
~0.29) before settling on 0.35 as a safe floor above that noise; an
initial 0.25 attempt collapsed a full test's worth of distinct filler
notes into one entry before this was caught.

Verified: seven direct unit tests (reinforce collapse, reinterpret-
in-place, genuinely-distinct append, scan-window boundedness, access-
aware consolidation sparing a reinforced note, `to_dict`/`from_dict`
round-trip, legacy-snapshot backfill with no `memory_access` key at
all); two production-path tests through the real engine-attached
`village_pillar` and a real `World.to_dict()`/`from_dict()` round-trip;
pyflakes clean; 4,000-tick LLM-disabled soak with clean round-trip;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
— pure Python, no native module touched.

## [1.34.65] — B4 reverse-direction disagreement classification (Tier 3 item 23)

Explicit user instruction: "Start completing items from roadmap." Picked
Tier 3 item 23, the roadmap's own named gap: only the Nature→Village B4
message arrow checked whether the RECEIVING pillar already held a
confident, conflicting theory about the same subject — every other
arrow defaulted to a flat kind tag regardless of what the receiver
already believed.

Extended the same mechanical `pillar.disagrees_with(subject)` check
(reused verbatim, not reimplemented) to five more arrows:

- Village→Innovation's `theory` arrow (`_maybe_schedule_beliefs`):
  checks `innovation_pillar.disagrees_with(entry["subject"])`.
- Innovation→Village's three `discovery` arrows sourced from `world.
  ontology.register_concept` — propose (`_maybe_schedule_ontology_
  proposal`), merge and evolve (both inside `_maybe_schedule_ontology_
  evolution`): each checks `village_pillar.disagrees_with(name)`.

`composite_entity`'s Innovation→Village arrow (naming an existing
standing building after a place/landmark) was deliberately left as a
flat `discovery` — it isn't a competing THEORY about a subject in the
sense `disagrees_with` means, so the check would be meaningless there,
not merely unattempted.

Verified via two direct production-path tests driving the real
`_maybe_schedule_ontology_proposal` job end to end (real season-
boundary gate, real backpressure/pillar-cycle checks, real RNG roll,
a stubbed synchronous `LLMAdapter.generate_json`) rather than calling
internals directly: one with a pre-seeded conflicting Village theory
confirmed the arrow now sends `disagreement`; one without confirmed it
still sends the original flat `discovery`. `MESSAGE_KINDS` already
included `"disagreement"`; no schema change.

Verified: pyflakes clean (same 4 known false positives); 4,000-tick
LLM-disabled soak with clean `to_dict`/`from_dict` round-trip;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
no native module touched.

## [1.34.64] — Full codebase + docs audit: two real bugs fixed, docs reorganized, roadmap checklist

Explicit user request: "audit the whole codebase and the docs as well.
Find and fix errors that have not been noticed, obvious bugs and subtle
bugs. Moreover, clean up the written documents, there are so many and
so confusing, clean them and remove the unnecessary ones. Finally,
update the roadmap file with a checklist of remaining open tasks."

Three deliverables. No feature work.

### Bug 1 — floods were structurally impossible (real, high impact)

`disasters.FLOOD_HEAVY_RAIN_PRECIPITATION` was `0.65`. Measured across
328,500 real `compute_weather` samples (3 seeds x 3 FULL years),
precipitation clears that bar on **0.01% of ticks**, `flood_pressure`
never left `0.0`, and no flood ever fired — a fully-built subsystem
(tile submersion, building/vehicle damage, farm destruction, A11
recurrence erosion, M2/M8's flood-reshapes-terrain work) guarded by
dead code.

Root cause is a textbook instance of this codebase's own standing
"unreachable threshold" lesson. The original `0.4` genuinely *was*
broken — it ratcheted `flood_pressure` to its cap and held it there,
so flooding read as constant background weather. v0.88.0's "v1 audit"
fixed that by changing **two** things at once: raising the bar to
`0.65` AND rebalancing `FLOOD_PRESSURE_GAIN`/`DECAY` from
`0.05/0.02` to `0.04/0.03`. Only the second change was needed; the
first overshot past what `compute_weather`'s EMA smoothing can reach.

Re-derived by simulating flood pressure against the real weather
sequences at the current gain/decay:

    bar   precip clears   pressure elevated   crossings   flood rolls
    0.65      0.01%             0.00%              0             0
    0.55      2.90%             0.00%              0             0
    0.50      9.99%             2.44%            272          ~13/yr
    0.45     22.90%            24.64%            122         ~136/yr
    0.40     40.94%            41.77%            243         ~228/yr

(The last column is an upper bound — the model omits the
`flood_pressure *= 0.5` relief a real flood applies on firing.)

Confirmed end-to-end against the real function, not just the model:
driving `tick_flood` on a real world for a full sim year (36,500 ticks,
907 water tiles) at 0.50 produced peak pressure 1.63, **4 genuine flood
events**, and 78 ticks with a tile actually submerged — rare and
consequential, and comfortably below the model's upper bound exactly as
the omitted pressure relief predicts.

`0.55` is also structurally dead (a 2.9% duty cycle never accumulates
25 net gains in a row); `0.45` and below re-create the original
ratchet. **Set to `0.50`** — the only value producing a real,
self-clearing flood season. The constant's docstring now carries the
full table.

**Methodology correction, recorded because it nearly shipped two wrong
fixes.** The first probes in this pass used 9,000-tick runs. At 100
ticks/day that is ~90 days — **spring only**, the driest quarter — and
`SimClock.month_name` is capitalized while `_MONTH_BASELINES` is
lowercase-keyed, so a per-month breakdown came back silently empty.
On that bad sample this pass had concluded `0.40` was correct (it is
not; it ratchets) and that `weather.py`'s six sky bands had drifted
out of calibration and needed retuning. Re-measured over full years,
the sky bands land at clear 30.07% / partly_cloudy 24.82% / overcast
22.11% / drizzle 12.86% / light_rain 7.17% / heavy_rain 2.97%,
dry 77% / rain 23% — matching v0.87.12's stated intent (29/24/21/12/
7/3, dry ~74%) almost exactly. **The sky bands were correct and the
proposed retune was reverted**; it would have made the world rain 43%
of the time. Both the flood docstring and the roadmap now record that
any threshold work here must sample all twelve months.

### Bug 2 — native/fallback float divergence (misdiagnosed since v1.34.0)

`scripts/verify_native_soak.py` has reported a permanent MISMATCH on
seed 3 since v1.34.0, annotated in every release since as "a known
pre-existing `river_tiles`/`roads.ever_established` set-ordering
quirk." **That attribution was wrong.**

Both sets were serialized in iteration order, which is genuinely not
meaningful, so both are now sorted at their `to_dict` sites — but that
did not clear the mismatch. Bisecting the actual `World.to_dict()`
diff at the first diverging tick isolated a single field,
`hydrology_field.moisture`, differing by exactly 1 ULP
(`0.41714033920812077` vs `0.4171403392081207`).

Traced upstream to `cpp/src/weather.cpp`. Built with `-march=native`
and GCC's default `-ffp-contract=fast`, the EMA blend
`prev*s + target*(1-s)` is fused into a single FMA, which retains more
intermediate precision than the two separately-rounded multiplies the
Python fallback performs. Weather feeds `HydrologyField.moisture`,
which is serialized unrounded, so a 1-ULP arithmetic difference became
a visible full-state divergence.

Fixed by adding **`-ffp-contract=off`** to `setup.py`'s
`_EXTRA_COMPILE_ARGS`. The surrounding comment there already worried
about floating-point semantics but stopped at `-Ofast`, missing that
contraction is on by default. Direct verification: `compute_weather`
native-vs-fallback is now bit-identical across 2,000 consecutive
ticks (it diverged at tick **1** before), and seed 3 — the reference
failing case — now MATCHes at 1500 ticks. **This flag is load-bearing
for every current and future native module doing `a*b + c*d`.**

### Dead code removed

Verified unreferenced across the whole package before removal
(pyflakes clean afterwards, only the four known string-annotation
false positives remain):

- `agents/population.py` — `DEVELOPMENT_BASELINE`, `INJURY_BASELINE`,
  `STRESS_BASELINE`, `SLEEP_DEBT_BASELINE`, `TRAIT_NOTABLE_THRESHOLD`,
  `OCCUPATION_DIALOGUE_REGISTER`, `OCCUPATION_SHOPKEEPER`,
  `OCCUPATION_WORKPLACES`, and an unused `MineralKind` import.
- `simulation/engine.py` — `agent_memory_log_count`,
  `recent_agent_memory_log`, `INVENTION_REDISCOVERY_CHANCE`, and a dead
  `festivals = festival_target.festivals` assignment.
- `world/state.py` — unused `apply_dry_lakebed_scar` import (the
  feature itself is correctly wired; `hydrology.py` does the applying).
- `llm/recorder.py` — unused `import zipfile`.

### Checked and deliberately NOT "fixed"

Recorded so a future audit doesn't re-flag them: four pyflakes
"undefined name" hits are string type annotations (`"Agent | None"`,
`"Building | None"`, `"Institution"`); `engine.py:2138`'s closure
correctly captures `sid`/`fb` as default args; `Agent.fertility` is a
documented derived property, correct to be write-free;
`World::settlement` / `WildlifeGrid::id` are nested/legacy keys, not
asymmetries. Four custom AST checkers written for this pass (closure
late-binding in loops, `to_dict`/`from_dict` key asymmetry, collection
mutation during iteration, out-of-range probability constants) came
back clean or false-positive-only.

Also verified reachable, not a bug: `STORM_WIND_THRESHOLD=0.55` fires
on 3.18% of ticks over a full year. The spring-only probe made it look
like 0.48%; it is fine.

### Docs cleanup

`docs/` went from 20 top-level files to 11 plus an `archive/`
subdirectory. **Nothing was deleted** — nine finished documents moved
to `docs/archive/` via `git mv`, preserving history:
`AUDIT-2026-07-20.md`, `IDEAS-2026-07-EMERGENCE.md`,
`DEFINITIVECHECKLIST-2026-07-21.md`, `REVIEW-2026-07.md`,
`VISION-2026-07.md`, `VISION-2026-07-LEARNING.md`, `ROADMAP.md`,
`CHANGELOG-ARCHIVE.md`, `DECISIONS-ARCHIVE.md`. Each is internally
marked fully shipped or historical record; each still explains why a
large part of the system looks the way it does, which is why they are
archived rather than removed.

New **`docs/README.md`** is the index the user's "so many and so
confusing" complaint actually asked for: a "start here" table (which
file answers which question), a live-documents section separating
still-governing docs from vision docs kept only for the standing rules
CLAUDE.md cites, an archive table with a status column, and the
project's own filing conventions.

Path references were updated in **live** documents (CLAUDE.md,
README.md, the roadmap and its siblings), including four that a plain
`sed` missed because the path was wrapped across two lines. References
inside `CHANGELOG.md` and the archives themselves were **deliberately
left alone** — those are historical statements about where a file was
at the time, and rewriting them would falsify the record.

### Roadmap checklist

`docs/ROADMAP-2026-07-REMAINING.md` gained an **"Open-task checklist"**
section near the top — the fast read the 2,400-line document never had.
Only open items appear, grouped by the doc's existing tiers (0, 0.5, 1,
1.5, 2, 3, 4, 5, the C++ backlog), plus two sections that did not exist
before: **"Known scope trims"** (real deliberate decisions recorded so
they are not rediscovered as gaps — districts outside
`carrying_capacity`, A19's battles axis having no combat mechanic to
source it, A13's ore reactant, LoRA staying data-collection-only) and
**"Standing verification debt"** (this pass's own findings). Derived by
re-reading every per-item status note against current source; two stale
notes were caught and corrected in the process.

### Verification

- pyflakes clean across `hearthmind/` (four known false positives).
- 4,000-tick LLM-disabled soak with a clean `to_dict`/`from_dict`
  round-trip.
- `scripts/verify_native_soak.py` — seeds 1,2 at 800 ticks MATCH, and
  seed 3 at 1500 ticks now MATCHes for the first time since v1.34.0.
- `compute_weather` native-vs-fallback bit-identical over 2,000 ticks.
- Flood threshold re-derived against 328,500 full-year weather samples;
  sky bands re-verified against the same sample before reverting the
  proposed retune.

## [1.34.63] — Tier 3 item 18: dialect grammar made genuinely recursive

Explicit user instruction: "Start 18" (docs/ROADMAP-2026-07-
REMAINING.md, Tier 3 item 18, A7 "Grammar-based procedural systems").
The item bundles three asks; this ships the one unambiguous, self-
contained piece — a real recursive rewrite system, not a single rule
application — over the smallest of the three existing domains.

`world/dialect_grammar.py`'s `drift_term` gained an optional `steps`
param (default 1, reproducing the prior single-application behavior
exactly for every existing call site). Internally, `_drift_once` is
the original rule-application logic factored out; `drift_term` now
chains `steps` rounds, each round choosing its rule off the STRING
PRODUCED BY THE PREVIOUS ROUND (`_stable_choice` reads the current
term, not the origin term) — a genuine production chain, not the same
mutation repeated. Clamped to `[1, MAX_DRIFT_STEPS=4]`; a round that
can't further change the current string stops early.

New `SettlementCulture.lineage_depth` (0 for the founding settlement,
`Settlement` gained a matching facade property + `to_dict`/`from_dict`
round-trip, legacy-backfill-safe): `SimulationEngine._maybe_schedule_
fission`'s apply() now sets `new_settlement.lineage_depth = home.
lineage_depth + 1` and passes it as `drift_term`'s `steps` — the one
real consumer this domain already had (a daughter settlement's
inherited lexicon terms). A granddaughter settlement (lineage_depth 2)
now genuinely drifts its inherited words two compounding rounds,
reading as further removed from the original coinage than a first-
generation daughter's one round — real lineage distance, not a flat
mutation regardless of how many fissions removed. UI: a conditional
"Lineage" stat tile (`N fissions from the founding settlement`),
alongside the existing A7 "Layout" tile.

The other two named A7 pieces were re-examined, not silently dropped:
layout/architecture staying single-application (a real graph grammar
over terrain/roads, a real recursive shape grammar) is a genuinely
larger lift each, left open; ritual/recipe-structure grammar, on
inspection, actually contradicts an earlier real design decision
(`docs/MASTERCHECKLIST-2026-07-22.md`'s own A7 entry: "ritual/recipe...
closer to meaning, the doc's own carve-out for staying LLM-authored")
rather than being an overlooked gap — left unattempted for that
reason, not effort. Rules becoming LLM-proposable also unattempted.

Verified: direct unit tests (`drift_term`'s `steps=1` exact backward
compatibility, genuine multi-round divergence across six sample terms,
clamping past `MAX_DRIFT_STEPS`, empty/whitespace safety); a `Settlement`
round-trip test for `lineage_depth` (including legacy-snapshot
backfill to 0); an isolated but real-function reproduction of the
fission call site's exact two-line addition (constructing daughter/
granddaughter `Settlement`s and confirming `drift_term(term, steps=
lineage_depth)` produces genuinely different, correctly-ordered
results) — a full live trigger of `_maybe_schedule_fission` through
every one of its real preconditions (crowding, an ambitious leader,
party assembly, a qualifying distant site) proved too many-precondition
to force reliably in this environment, same class of difficulty as
other multi-gated jobs; the call-site logic itself was verified
directly instead. A 4000-tick LLM-disabled engine soak with a clean
round-trip; `scripts/verify_native_soak.py` (seeds 1,2 x 800 ticks)
byte-identical — pure Python, no native module touched.

## [1.34.62] — Tier 3 started: A5/A6's validate-step half; Tier 4/5 queued

Explicit user instruction: "Start tier 3 and queue tier 4 and 5"
(docs/ROADMAP-2026-07-REMAINING.md). Tier 4 ("standing discipline,
re-audit periodically") and Tier 5 (HearthBench & the Adaptive
Runtime) are formally queued for a future turn's explicit instruction
— no code from either attempted this pass, per the doc's own standing
convention.

Tier 3 item 17 (A5/A6, "Capabilities/affordances over object
classes"/"Exposed affordances for discovery"): the generate-step half
(grounding Innovation's proposal prompt in real standing-building
affordances/reactions) shipped at v1.16.0/v1.18.0; the validate-step
half — "Innovation's deterministic re-verification, cross-checking a
PROPOSED concept's claimed mechanism against this layer," explicitly
flagged as unattempted in both `world/affordances.py`'s own module
docstring and the roadmap doc — ships now.

`llm/ontology.py`'s `validate_hook` gained an optional `present_tags`
param (default `None`, every pre-existing call site unchanged): an
`invention_specialization_category` hook claiming `agricultural`/
`structural` is now rejected (degrades to no mechanical effect, same
as any other invalid hook) when the settlement has zero real
affordance overlap against a new `SPECIALIZATION_AFFORDANCE_HINTS`
mapping. `mercantile`/`general` have no meaningful physical-affordance
mapping (trade/currency isn't a physical affordance, and MARKET/BANK-
shaped buildings correctly carry no affordance tag at all per that
module's own docstring — gating them would be a category error, not a
real check) and stay unchecked, same as before this pass. `parse_
propose` threads the param through; `SimulationEngine._maybe_schedule_
ontology_proposal`'s `apply()` passes the SAME `present_tags` already
computed for the generate-step's grounding (a closure capture, not a
second query) — zero added cost. `llm/composite_entity.py`'s own
`validate_hook` call site is left at the default (unwired) — flagged,
not attempted, out of this pass's scope.

Still open, explicitly not attempted this pass: per-instance `Entity.
affordances`/`Entity.properties` as a genuine per-instance field
generalized beyond buildings (today: class-level `dict[BuildingKind,
...]` only) — a larger, separate piece of item 17.

Verified: direct unit tests (`validate_hook`'s `present_tags` param —
no-overlap-rejects, real-overlap-accepts, `mercantile`/`general`
always-pass, other hook types unaffected, `None` reproduces old
behavior); two production-path tests scheduling the real
`_maybe_schedule_ontology_proposal` against a forced fallback claiming
an `agricultural` specialization — once against a settlement with no
matching standing buildings (hook correctly rejected) and once with a
real standing GRANARY added (hook correctly accepted); a 4000-tick
LLM-disabled engine soak with a clean round-trip (no new persisted
state — this is a pure prompt/validation-logic change); `scripts/
verify_native_soak.py` (seeds 1,2 x 800 ticks) byte-identical.

## [1.34.61] — B5 + C4: evolve/merge hypothesis loop, a second acceptance-gate auditor

Explicit user instruction: "Start B5 and C4" (docs/ROADMAP-2026-07-
REMAINING.md, Part B/Part C, Tier 2 items 15/16).

B5 "Innovation as conscious scientist": direct code inspection found
the item's own text stale — the affordance/reaction query half
(`discoverable_combinations`/`discoverable_reactions` grounding
`_maybe_schedule_ontology_proposal`'s prompt) was already wired at
v1.16.0/v1.18.0, well before this roadmap section was written; not a
real gap. The genuinely open half: only `propose` closed the
hypothesize -> observe -> revise loop (`InventedConcept.hypothesis`/
`world_model_entry_id`, `world.ontology._record_hypothesis_outcome`) —
`evolve`/`merge` registered their concepts with no hypothesis and no
mirrored entry to later revise. `llm/ontology.py`'s `SYSTEM_PROMPT_
EVOLVE`/`SYSTEM_PROMPT_MERGE` now ask for the same optional
`hypothesis` field `propose` already does (`parse_evolve`/`parse_merge`
now return `(name, description, hypothesis)`; `fallback_evolve`/
`fallback_merge` carry a matching "no specific reason" sentinel —
empty-string is a legitimate common answer, most evolutions/merges are
natural drift, not a claimed fix). `SimulationEngine._maybe_schedule_
ontology_evolution`'s two branches now mirror-then-register in the same
order `ontology_proposal`'s apply() does (confidence 0.4, not the
prior flat 1.0 "observation" — a real behavioral change: an evolved/
merged concept's initial belief is now framed as a genuine hypothesis,
consistent with how a proposed concept already reads), so the child
concept's own later real adoption fate can revise Innovation's belief
about it in place exactly like `propose` already does. Zero added LLM
call volume — one more field on an existing response shape.

C4 "The acceptance gate as law": the runtime-auditor half ("reject
persistent state no system observes") already existed for one type
(`TriggerRule`, via `ontology.retire_stale_rules`, item 5.1) but had
no second instance. `world.reactions.CompositeReaction` is its
structural sibling — same `status`/`fire_count`/`last_fired_tick`
shape, LLM-plus-sandbox authored the same way (A18's second slice) —
and had none. New `reactions.retire_stale_composite_reactions`
(`COMPOSITE_REACTION_STALE_TICKS=40_000`, same value/reasoning as
`TRIGGER_RULE_STALE_TICKS`) retires an `active` reaction whose
condition-set has never once matched past the stale window; "Desperate
Times" (`origin_settlement_id=None`, the one hand-authored reaction) is
exempt, same "world-original, not a failed proposal" carve-out this
codebase already uses elsewhere. Run on `_maybe_schedule_composite_
reaction_propose`'s own gated cadence — the same "run it on this job's
own cadence" precedent `rule_propose` established for its sibling
auditor. New `composite_reactions_total`/`_by_status` dev-console
diagnostic fields, same depth as `trigger_rules_total`/`_by_status`. A
fully general auditor covering every persistent-state type in the
codebase remains unattempted — this closes the item by giving the
pattern a real second instance, not by generalizing the mechanism.

Verified: direct unit tests (`parse_evolve`/`parse_merge`'s hypothesis
field incl. the empty-sentinel case; a fake-pillar `_record_hypothesis_
outcome` confirm-path test for a merge-originated concept reaching
`established`; `retire_stale_composite_reactions`' stale/not-stale/
already-fired/`origin_settlement_id=None`-exempt cases); two
production-path tests scheduling the real `_maybe_schedule_ontology_
evolution`/`_maybe_schedule_composite_reaction_propose` methods against
a real `SimulationEngine`, confirming a genuinely evolved/merged
concept carries a real `world_model_entry_id` and a genuinely stale
composite reaction gets retired through the actual job cadence; a
4000-tick LLM-disabled engine soak with a clean round-trip; `scripts/
verify_native_soak.py` (seeds 1,2 x 800 ticks) byte-identical — pure
Python, no native module touched. A seed-3 divergence at tick 383 was
investigated and confirmed pre-existing on unmodified `origin/claude/
hearthmind-overview-5bekay` via `git stash`, not introduced by this
batch (same documented `river_tiles`/`roads.ever_established` set-
ordering class of quirk noted since v1.34.0).

## [1.34.60] — A17: a second real memetics consumer, personal tradition-keeping

Explicit user decision, via `AskUserQuestion` after the v1.34.59
re-audit: "Design a new memetics consumer" — invent a genuinely new
candidate-list-shaped propagation mechanism from scratch (no existing
site had the right shape) so `world/memetics.py`'s `weighted_spread_
target` gets a second real production consumer, matching how ontology
concept adoption already uses it.

New `Agent.kept_traditions` (`agents/agent.py`, plain Python list,
FIFO-capped at `KEPT_TRADITIONS_CAP=5`, round-tripped): `Settlement.
traditions` are settlement-wide strings with no notion of who
personally lives by one — this is that missing per-person layer. New
`SimulationEngine._maybe_spread_tradition_keeping` (`simulation/
engine.py`, wired into `_TICK_JOBS` right after `_maybe_spread_
concepts`): a small per-tick, per-named-settlement roll (`TRADITION_
KEEPING_SPREAD_CHANCE_PER_TICK=0.02`, same order of magnitude as
`CONCEPT_SPREAD_CHANCE_PER_TICK`) picks one of that settlement's
traditions and uses `memetics.weighted_spread_target` to choose its
next personal keeper from candidates who don't already keep it,
weighted by real social-graph closeness (fondness/trust) to existing
keepers — carriers empty (a tradition's very first personal keeper)
degrades to uniform via memetics' own baseline weight, same as
ontology's proven mechanism.

Real consequence, not flavor: `world/culture_aggregate.py`'s
`compute_civilization_culture` gained an optional `agents` param and a
new `tradition_keeping_rate` field — the fraction of a named
settlement's living population who personally keep at least one
tradition, distinct from `total_traditions_established`'s bare paper
count. It nudges `cultural_cohesion` up by at most `TRADITION_
ENGAGEMENT_COHESION_WEIGHT=0.15`, never dominating the existing
settlement-level dominant-category agreement signal. Both call sites
(`World.summary()`'s broadcast, `SimulationEngine._maybe_schedule_
consciousness`'s Town Consciousness grounding) now pass `self.world.
population.agents` through. UI: the main-UI "Civilization" stat tile
gained a "(N% personally keep a tradition)" suffix; the NPC inspector's
Personality section gained a conditional "keeps: ..." line.

The other two A17 pieces (a fitness-vs-truth axis for rumors; a shared
mutate/decay/compete step over lexicon/topics) were out of scope of
this specific decision and remain exactly as flagged in v1.34.59 —
docs/ROADMAP-2026-07-REMAINING.md's A17 section records both.

Verified: direct unit tests for `compute_civilization_culture`'s new
`agents` param (rate computation, cohesion nudge bounded, backward-
compatible `agents=None`/omitted), a production-path test scheduling
the real `_maybe_spread_tradition_keeping` job against a settlement
with a real tradition and multiple agents confirming a keeper is chosen
and capped correctly, a 4000-tick LLM-disabled engine soak with a clean
`to_dict()`/`from_dict()` round-trip (including a legacy-snapshot
backfill check for agents with no `kept_traditions` key), `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical — pure
Python, no native module touched (`Agent.kept_traditions` is a plain
compatibility-shim attribute, not store-backed, same as `hardened_
traits`) — and a live dev server + Playwright pass confirming the
Civilization tile suffix and NPC inspector line both render correctly.

## [1.34.59] — A17 re-audit: three blockers filed, no code shipped

Explicit user instruction: "Continue A17." Docs-only — investigation
found each of the item's three remaining named pieces carries a real,
flagged blocker rather than being simply unattempted, and forcing code
through any of them this pass would have meant either inventing a
mechanism with no real content-type home or contradicting a standing
design principle. Filed as an explicit audit finding rather than
guessed at:

1. A second consumer for `memetics.weighted_spread_target` (folding
   rumor/tradition/song/technique onto the propagation weighting
   ontology already uses): re-checked every `rng.choice`/`rng.sample`
   site in `population.py`/`engine.py` — none match the needed shape
   (pick one next carrier from a candidate list weighted by closeness
   to existing carriers). No second site of this shape exists today;
   one would need to be designed from scratch.
2. A fitness-vs-truth axis for rumors needs a real ground-truth value
   per rumor to demonstrate against — directly in tension with Phase
   G's standing principle that belief is never required to reconcile
   with objective reality (CLAUDE.md, "per-person beliefs, trust,
   gossip"). Needs an explicit user call, not a unilateral code change.
3. A shared mutate/decay/compete step: `Settlement.lexicon`'s only
   live consumer is `llm/dialogue.py`'s general `build_prompt`, dead
   code since v1.4.0 (real dialogue only uses `build_voice_prompt`) —
   not a meaningful production proof. `recent_topics`/`top_topics()`
   is genuinely live but reworking its FIFO eviction risks
   destabilizing the topic-diversity tuning v0.87.35 fixed against
   monoculture — not attempted without a live-diagnostic read first.

`docs/ROADMAP-2026-07-REMAINING.md`'s A17 entry updated with the full
findings; work resumes only on an explicit user decision naming one of
these three paths (or a new angle).

## [1.34.58] — A13 CLOSED: the real automatic reaction reactor

Explicit user instruction: "update roadmap if A20 is closed otherwise
complete it. Start A13." A20 was already closed in v1.34.57 — fixed a
stale summary-index line the prior batch missed. A13 ("Chemistry /
reaction system") previously shipped the query half only
(`discover_reactions`, read-only); this ships the spec's own literally-
named remainder — a `ReactionRule(reactants, conditions, products,
rate)` engine that fires automatically on the tick loop and mutates a
standing building's actual material.

`ReactionRule` gains a `rate` field (consecutive ticks required,
default 500, comparable order of magnitude to `terrain_evolution.
MINING_SCAR_QUARRY_TICKS`). New `Building.material`/`reaction_
progress` (per-INSTANCE fields — `material=None` means "use `world.
materials.BUILDING_MATERIALS[kind]`'s default," the state of every
building that was never converted). New `world.chemistry.tick_
building_reactions`, called once per settlement per tick from `World.
tick()`: settlement-wide condition presence (same affordance-union
model `discover_reactions` already used) but per-BUILDING reactant
match and sustained-progress counter — a standing building whose
effective material (`world.materials.effective_material_name`)
matches a rule's reactant, held under that rule's condition for `rate`
consecutive ticks uninterrupted (reset, not paused, on any
interruption — same discipline as `terrain_evolution.maybe_form_
quarries`), genuinely converts. Only clay (SHRINE) and fiber
(PASTURE/HATCHERY) can ever fire this way — no `BuildingKind` defaults
to `ore`, so ore->metal stays reachable only through the query half,
an honest gap, not silently worked around.

Two real consequences, both chosen specifically to carry ZERO native-
parity risk (this function runs entirely outside the native-ported
building-decay tick, never inside it): a one-time `REACTION_
CONDITION_BOOST` to the building's `condition` on conversion, and new
`world.materials.building_instance_affordances` — every future
affordance/material query for that specific instance now reflects the
NEW material's real derived properties, not the kind's stale default.
Wired into Innovation's `discover_reactions`/`discover_combinations`
query (now per-instance, was per-kind) and the building-descriptor UI
line. UI: the click inspector's "Built of" line reads the real
per-instance material (flagging a converted building explicitly), new
🏺 `material_converted` event icon/filter group.

Verified: direct unit tests (full conversion cycle for both real
reactant paths, interruption resets not pauses progress, no re-firing
once converted since the product has no further `REACTION_RULES`
entry); a production-path test driving the real `World.tick()` loop to
a genuine conversion; a `to_dict()`/`from_dict()` round-trip (material
preserved) plus a legacy-backfill test (missing keys default to
`material=None`/`reaction_progress=0`); a production-path smoke test
confirming `_maybe_schedule_ontology_proposal` doesn't crash with a
converted building present; a 5000-tick organic LLM-disabled engine
soak with a clean round-trip (the one surviving diff, `river_tiles`
set-ordering, reproduced identically on unmodified code via `git
stash` — the same pre-existing quirk CLAUDE.md's v1.34.0 entry already
documents, not introduced here); `scripts/verify_native_soak.py` (2
seeds x 800 ticks) byte-identical; a live dev server + Playwright pass
confirming no console errors.

## [1.34.57] — A20 CLOSED: culture aggregates settlements' information-ecosystems

Explicit user instruction: "Unify folklore/legend pipeline and continue
A20." Two independent slices in one batch.

**Folklore/legend unification (A21's last flagged-open gap).** New
`Settlement.folklore_persistence_count`/`folklore_persistence_
promoted`: a folk tale that endures — keeps NOT being superseded by
something newer, across `FOLKLORE_LEGEND_PERSISTENCE_THRESHOLD=6`
consecutive monthly folklore-job firings (empty rumor window, an LLM
"not worth telling" answer, or a near-duplicate rejected by `folklore.
parse_folklore`'s dedup) — deterministically graduates into `Settlement.
legends` via new `SimulationEngine._promote_folklore_to_legend`, zero
LLM cost (the tale's wording is already settled; this is a status
change, not a new narration). Feeds the same `pattern_signal_counts`
pressure gate v1.34.54 wired for Emergence-sourced legends. This is the
real fold the two previously-parallel pipelines (folklore's rumor-
condensation chain, `legends`' Emergence-API chain) never had — a tale
that keeps being retold long enough IS a legend, exactly the "temporal
compression" the item names.

**A20 "Multi-scale simulation" — CLOSED.** Direct code audit found the
doc's own status line stale: `world/fields.py`'s `FieldGrid` gained
five more region-aggregated fields since v1.27.0 (disease_pressure/
pollution/traffic/scarcity), each the same "region is a computed
summary of its tiles" shape as `population_density` — the spec's first
named gap was already satisfied several times over, just never
reflected back into the doc. The genuinely open half ships now: new
`world/culture_aggregate.py`'s `compute_civilization_culture` (pure
aggregation over already-real per-settlement `culture_effects`/
`religion`/`legends`/`traditions_established`, zero new simulation,
zero LLM cost) — dominant tradition-influence category world-wide,
cultural cohesion (fraction of settlements sharing it), religions
formed, total legends, total traditions established. Real consumer:
`llm/consciousness.py`'s Town Consciousness prompt (the one genuinely
world-scoped Mind) gains an optional `civilization_culture_text`
grounding line. UI: `World.summary()`'s new `civilization_culture`
field, a plain-language "Civilization" main-UI stat tile.

Verified: direct unit tests for both new mechanisms (persistence/
promotion threshold crossing, cohesion math across cohesive/divergent
settlement mixes, empty-world/no-settlement edge cases); production-
path tests through the real `_maybe_schedule_folklore`/`_note_
folklore_persistence`/`_promote_folklore_to_legend` and `_maybe_
schedule_consciousness` call paths (including the real `Population.
_maybe_start_construction`-shaped forced-scenario pattern this
project's tests already use); a 5000-tick LLM-disabled engine soak
with a clean `to_dict()`/`from_dict()` round-trip and legacy backfill
(civilization_culture is summary-only, never persisted); `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical — pure
Python, no native module touched; a live dev server + Playwright pass
confirming the "Civilization" stat tile renders with the correct
plain-language text.

## [1.34.56] — A21 third slice: legend grounding reaches tradition/religion formation

Explicit user instruction: "Continue A21" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 2, "Temporal compression"). v1.34.54's second
slice grounded chronicle/folklore in "already legendary" context and
fed legend formation into `pattern_signal_counts` (Innovation's
ontology-proposal pressure gate) but left the checklist's own literal
wording — "a formed legend doesn't yet feed back into tradition/
religion/institution formation" — only partially closed: nothing that
actually AUTHORS a tradition or a religion ever read a settlement's
own legends.

`llm/culture.py`'s `build_prompt` (the tradition-authoring job) and
`llm/religion.py`'s `build_prompt` (ritual->religion crystallization)
both gained an optional `legends` param, same additive "omitted or
empty reproduces the prior prompt exactly" shape chronicle/folklore
already established — a new tradition or a crystallizing religion can
now genuinely ground itself in a legend the village already holds as
true ("a festival honoring the subject of a real myth," "a religion
coalescing around what the village already believes happened"), not
just recent raw events. Wired at both real call sites (`_maybe_
schedule_tradition`/`_maybe_schedule_religion` in `simulation/
engine.py`) via `list(target.legends)`. Institution formation itself
(COUNCIL/GUILD/FACTION) has no natural grounding hook to extend this
way — those form from deterministic triggers (trust-graph clustering,
skill mastery counts), not an LLM authoring step reading settlement
narrative context — so that piece of the checklist's wording stays
covered by v1.34.54's `pattern_signal_counts` feedback into ontology
proposals, the nearest real "institution-adjacent" LLM decision point.
Folklore/legend pipeline unification remains explicitly open, per the
checklist's own "aspirational, not attempted this pass" framing.

Verified: direct unit tests for both `build_prompt` functions (legend
text present when supplied, byte-identical prompt when omitted); a
production-path smoke test scheduling both real jobs
(`_maybe_schedule_tradition`/`_maybe_schedule_religion`) against a
settlement with a real legend, LLM disabled, confirming no crash and
correct fallback application; a 4000-tick LLM-disabled engine soak
with a clean `to_dict()`/`from_dict()` round-trip (no new persisted
state — pure prompt-construction change); `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical.

## [1.34.55] — A19 third slice: construction/ownership close the spatial-memory axis list

Explicit user instruction: "Continue with A19" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 2, "Persistent spatial memory"). v1.34.53's second
slice explicitly flagged `construction`/`ownership` as needing "a
genuinely new per-tile HISTORY store" not yet built — this slice builds
it, closing the item.

New `World.construction_history`/`ownership_history`: permanent,
non-decaying `dict[(x, y), int]` counts — deliberately NOT shaped like
the scar dicts (`mining_scars`/`disaster_scars`/etc., which decay
weekly), since "how many times built" and "how many times passed down"
are genuine accumulated history that shouldn't fade the way a cosmetic
mark should (same permanent-count shape `flood_recurrence_counts`/
`mining_scar_sustained_ticks` already established). Each is written at
an already-existing real mechanical event, not a new one invented to
populate the axis: `construction_history` increments in `Population.
_maybe_start_construction`, immediately after its real call to
`Settlement.start_construction`; `ownership_history` increments in
`Population._apply_inheritance` (H7), at the exact point a HUT's
`owner_agent_id` hands off to a living heir. Both dicts are threaded
through `Population.tick()` as optional keyword params (same pattern
`ruin_scars`/`road_scars` already use), `World.tick()` passes its own
instances, and both round-trip through `to_dict()`/`from_dict()` with
legacy-snapshot backfill (absent key -> empty dict).

`world/spatial_memory.py`'s `LOCATION_HISTORY_CATEGORIES` gains
`construction`/`ownership`; new `CONSTRUCTION_NOTABLE_COUNT=2` (a
single first-ever build is ordinary — it takes a real rebuild to be
worth naming) and `OWNERSHIP_NOTABLE_COUNT=1` (a real inheritance
hand-off is already rare — H7 needs a death with a living family heir —
so even the first occurrence is notable), each normalized 0..1 via
`min(1.0, count / threshold)`, same "absence means neutral" discipline
every other axis holds. `location_character_from_dicts`/`location_
character`/`LOCATION_CHARACTER_LABELS` all extended. This closes every
axis A19's own spec names except battles — no combat mechanic exists to
source it, the one axis that genuinely stays open (same note A18
already carries for its own "raid" example).

Verified: direct unit tests (below/at/above-threshold surfacing for
both new axes, absent-dict handling); two production-path tests
calling the real `Population._maybe_start_construction`/`_apply_
inheritance` classmethods directly with a forced scenario (two mature
founders staked into one construction site; a dying agent with a real
FAMILY-institution heir and an owned HUT) confirming both dicts
populate correctly through the actual mechanism and `location_
character` reflects the result; a 4000-tick LLM-disabled `World.tick()`
soak with a clean `to_dict()`/`from_dict()` round-trip, including a
legacy-backfill test against a snapshot missing both new keys;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
pure Python, no native module touched.

## [1.34.54] — A21 second slice: legend feedback + "already legendary" grounding

Explicit user instruction: "continue a21" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 2, "Temporal compression"), redirecting from the
queued Tier 3/Tier 0/Tier 5 sequence.

A21's first slice (v1.28.0) shipped legend detection/narration
(`world/legends.py`, `Settlement.legends`) but left both of the doc's
remaining named gaps open: legend feedback into tradition/religion/
institution formation, and using a formed legend as "already
legendary" grounding in other prompts. Both ship now.

Feedback: `_maybe_schedule_legend_detection`'s `apply()` now bumps
`Settlement.pattern_signal_counts[f"legend_{subsystem}"]` to
`PATTERN_SIGNAL_BELIEF_THRESHOLD` the moment a legend crystallizes —
the SAME pressure gate `_maybe_schedule_ontology_proposal` already
reads (`pressured`, `pressure_signal` naming), reused rather than
duplicated. A legend forming is real evidence its theme matters to the
village, so it now measurably biases what Innovation proposes next.

Grounding: `llm/chronicle.py` and `llm/folklore.py` both gained a
`legends` param. Chronicle's system prompt already invited using
folklore "if it fits" — legends get the same treatment, one more
optional lens. Folklore's is a real dedup signal: the model is told
explicitly which subjects are ALREADY a full legend (distinct from an
ordinary retellable tale), closing the gap where folklore's own
existing-tale dedup logic had no way to know a subject had already
been promoted a rung up.

`llm/dialogue.py` explicitly NOT touched — audited and found its
general `build_prompt`/`build_opportunity_candidates`/
`select_opportunities` machinery has been dead code since v1.4.0's
voice-pair redesign (real LLM dialogue only ever reaches the separate
`build_voice_prompt`, deliberately minimal per an explicit prior user
directive — "a very concise summary of the town," not the full
grounding apparatus). Widening it here would work against that
decision rather than extend it; recorded as a real finding, not a
silently skipped item.

Verified: unit tests (legend grounding present/absent in both
chronicle/folklore prompts), a real engine production-path test
(`SimulationEngine` with a forced 5-observation legend candidate,
confirming the exact `pattern_signal_counts` key/value the real
`apply()` closure writes correctly makes the settlement read as
"pressured"), a 4000-tick LLM-disabled engine soak with clean
round-trip, `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical — pure Python, no native module touched.

## [1.34.53] — A19 second slice: traffic/pollution/fertility join location_character

Explicit user instruction: "start A19" (docs/ROADMAP-2026-07-
REMAINING.md's Tier 2 item 10), followed by "queue tier3 and tier 0
and then tier 5" for subsequent turns.

A19's first slice (v1.34.49) unified six sparse per-tile scar/activity
dicts into `world.spatial_memory.location_character`, explicitly
flagging traffic/pollution/fertility as "a genuinely different shape"
(continuous `FieldGrid` regions / a farmed-tiles-only dict defaulting
to pristine, not sparse per-event dicts) and leaving them unfolded.
This pass folds all three in for real: `location_character_from_dicts`
gained `soil_fertility`/`traffic_at`/`pollution_at` keyword params
(new `FERTILITY_NOTABLE_THRESHOLD`/`TRAFFIC_NOTABLE_THRESHOLD`/
`POLLUTION_NOTABLE_THRESHOLD`, all 0.5 — only a genuinely worked-out/
busy/fouled reading surfaces, same "absence means neutral" discipline
every other axis already holds); `location_character(world, x, y)`
resolves `traffic`/`pollution` via `FieldGrid.get_at` for that
specific tile before calling through. Nine of the spec's named axes
are now real. Ownership/construction remain explicitly unfolded —
both need a genuinely new per-tile HISTORY store (a building's current
owner/stage is instantaneous state, not accumulated memory the way
every other axis is), real unscoped follow-up rather than another
read-side unification step. `Population._choose_build_site`'s existing
positional call site is untouched (all new params keyword-only,
defaulting to `None`).

Verified: direct unit tests (forced-value axis surfacing, below-
threshold absence, never-farmed-tile absence, category/label registry
completeness), a production-path test against a real `World` with
forced field/farm state confirming the correct region/tile values
reach `location_character`, a 4000-tick LLM-disabled engine soak with
clean round-trip (no new persisted state — read-side only, so nothing
new to serialize), `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical — pure Python, no native module touched.

## [1.34.52] — Elevation renders on the map, irrespective of biome boundary

Explicit user follow-up on v1.34.51: "Make elevation render on the
map somehow and hence the erosion. Irrespective of biome boundary."
Root gap: `Tile.elevation` was never rendered on the map at all —
every elevation-writing mechanism (A11's own weekly hydrology erosion,
v1.34.51's new quarry formation and flood-recurrence erosion) was only
ever visible when the change happened to cross a `classify_with_bias`
biome band; the much more common small nudge left zero map trace.

`interface/api.py`'s `set_terrain()` payload gained a full dense
`elevation` grid, read straight off `terrain` (the same source
`biomes` already reads — no new backend state, no new call-site
threading). `app.js`'s `drawStaticTerrain` now blends a subtle,
always-on relief tint into every tile — `elevationShadeStyle`,
centered near 0.6 (roughly the grassland/forest elevation boundary,
so ordinary mid-elevation land reads close to neutral), capped at
`ELEVATION_SHADE_MAX_ALPHA` (0.4) so it never overwrites a tile's own
biome color identity. A permanent map layer, not a togglable overlay
mode — matches the standing "the map is the primary interface" and
"every deterministic system should have SOME real map representation"
disciplines. Cumulative erosion below a single band-crossing threshold
is now genuinely visible as a gradually shifting shade rather than
invisible until (if ever) it crosses a band.

Docs: `docs/ROADMAP-2026-07-REMAINING.md`'s M2/M8 entry gained a
follow-up note; the "Erosion" stat tile's tooltip text updated to
describe the new always-visible relief shading instead of only
mentioning band-crossing.

Verified: `/terrain` payload directly inspected (dense 32x32 float
grid present, values matching `World.terrain`); a live dev server +
Playwright pass with a screenshot confirming visible relief shading
(dark deep-water basin, lighter highland patches) and no new console
errors; `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical — pure payload/rendering change, no native module or
persisted-state touched.

## [1.34.51] — M2/M8 closed: quarries + flooding permanently reshape the land

Explicit user instruction: "Complete M2/M8" — the one Tier 1.5 item
left flagged (not attempted) after v1.34.50's own docs-accuracy pass,
because building either of its two remaining named examples would
reverse a real, twice-documented prior design decision ("mining
scars/disaster scars are deliberately cosmetic-only, never a biome
change"). This explicit instruction is the product call that decision
was waiting on.

**Quarry scars as actual terrain change**: new `Biome.QUARRY`
(appended last in the enum, same native-storage-safe convention as
`RIVER`/`WETLAND`). `terrain_evolution.maybe_form_quarries` — a HILLS
tile mined CONTINUOUSLY, with no interruption, long enough to both
reach and then HOLD `MINING_SCAR_QUARRY_THRESHOLD` (0.95) for
`MINING_SCAR_QUARRY_TICKS` (400) converts permanently, with a real
elevation drop (`MINING_SCAR_QUARRY_ELEVATION_DROP`) — real quarrying
digs a pit. Deliberately scoped tight (well past ordinary mining's
existing cosmetic scarring) so this is a genuine reversal only for
sustained extreme extraction, not a blanket change to how mining
works. QUARRY is sticky against both climate drift (`_skip_climate_
drift`) and erosion's own elevation-driven reclassification (`hydro
logy_field.tick_erosion`'s `classify_with_bias` branch) — it never
silently reverts to HILLS. Skips a developed tile like every other
terrain mutator (`_is_developed`).

**Flooding reshapes the land**: every flood already had a temporary
submerge/restore cycle (a tile flips to `Biome.SHALLOW_WATER` for
`FLOOD_DURATION_TICKS`, then fully restores) — but that always fully
reverted, leaving no lasting trace no matter how many times a tile
flooded. `disasters.tick_flood` gained an optional `recurrence`
counter (per-tile flood count); once the SAME tile has flooded
`FLOOD_RECURRENCE_EROSION_THRESHOLD` (3) separate times, its next
recede applies a real, permanent elevation drop (`FLOOD_EROSION_
ELEVATION_DROP`) and reclassifies via `classify_with_bias` instead of
restoring the pre-flood biome — the same reclassification mechanism
A11's own `tick_erosion` already established, reused rather than
duplicated. `recurrence=None` (the default) reproduces the exact
prior always-fully-restores behavior byte-for-byte.

New `World` state: `mining_scar_sustained_ticks`/`flood_recurrence_
counts` (small, self-pruning progress dicts, same shape as every
other scar-tracking dict in this codebase), `tiles_flood_eroded_
total`/`quarries_formed_total` (monotonic counters, same shape as
`tiles_eroded_total`/`river_tiles_shifted_total`). New `quarry_
formed`/`flood_eroded` event categories, wired into `TERRAIN_
CHANGING_CATEGORIES` (Python + JS) so the map resyncs and the biome-
count cache invalidates correctly. UI: "Quarries" stat tile (a
currently-standing count plus an ever-formed total), a distinct map
color, the flood-erosion count folded into the existing "Erosion"
stat tile's readout, `quarry_formed`/`flood_eroded` event icons.

Verified: direct unit tests (`maybe_form_quarries`'s full lifecycle —
sustained-threshold gating, interruption resetting progress to 0 not
pausing it, developed-tile skip, the actual biome+elevation mutation;
`tick_flood`'s recurrence-triggered erosion firing after exactly three
floods of the same tile, confirmed via a real forced-flood scenario);
a `recurrence=None` backward-compatibility test confirming `tick_
flood`'s prior always-restores behavior is byte-for-byte unchanged
when the new param is omitted; a real `World.create_new`/`tick()`
production-path run (4000 ticks) with a clean round-trip and legacy-
backfill (both new dicts/counters default cleanly on a snapshot
missing the new keys); `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical — pure Python, no native module touched; a live
dev server + Playwright pass confirming the "Quarries" stat tile
renders and the map loads cleanly with no new console errors. Closes
Tier 1.5 "The Living Map" entirely — M2/M8 was its last open item.

## [1.34.50] — Tier 1.5: dry lakebeds + docs-accuracy pass

Explicit user instruction: "Start tier 1.5 and finish as many tasks
as possible in 1 turn." Found Tier 1.5 ("The Living Map") was already
almost entirely closed (M4/M6/M7/M10/M11-M12 all shipped in earlier
passes) — audited what genuinely remains rather than assuming
greenfield.

**Docs-accuracy fix**: the roadmap's own Tier 1 summary index still
said A3's rivers-re-carving "remains open" after A11 unblocked it —
stale; A3's own dedicated entry already recorded it shipped at
v1.34.25. Fixed the summary line. Also corrected Tier 1.5's M2/M8
status: the item's own named blocker (`Tile.elevation` immutability)
is resolved (A11 + A3), but its other two named examples ("flooding
reshapes the land," "quarry scars as actual terrain change") are
EXPLICITLY documented elsewhere as cosmetic-only by deliberate design
(`MINING_SCAR_GAIN_PER_TICK`'s and `apply_disaster_scars`'s own
docstrings) — reversing either is a real product decision, not a
mechanical continuation, so it's flagged for an explicit call rather
than silently attempted.

**Shipped**: M1/M9's own explicit "dried lakes... remain genuinely
unbuilt" line. `hydrology.tick_lakes`'s `lake_receded` branch used to
flip a vacated shoreline tile straight to BEACH with zero lasting
trace. New `World.dry_lakebed_scars` (same additive-decaying-dict
shape as `mining_scars`/`disaster_scars`/`ritual_activity`/
`ruin_scars`/`road_scars`/`migration_trails` — the sixth instance of
this exact pattern) marks a vacated tile; `tick_lakes` gained an
optional `dry_lakebed_scars` param (`None` reproduces the exact
pre-existing behavior/RNG stream for any caller without one in
scope). Seventh axis in `world/spatial_memory.py`'s `location_
character` unification. `hydrology.LAKE_MIN_TILES` means a lake never
fully vanishes, so this only ever marks individual vacated shoreline
tiles, never "a whole dried lake" — same honest, bounded scope as
every sibling axis. UI: new map overlay color (`paintDryLakebedScars`,
pale silty grey-blue, distinct from the road/migration tints), bare-
tile inspector line, "Dry lakebeds" stat tile — same full pattern as
every prior scar-axis slice.

Verified: direct unit tests (`apply_dry_lakebed_scar`/`decay_dry_
lakebed_scars`, `location_character_from_dicts`'s new param,
`location_character_text` rendering); a production-path test driving
`hydrology.tick_lakes` directly with a real shrinking lake, confirming
a genuine `lake_receded` event forms a real scar entry; a byte-
identical backward-compatibility check confirming `dry_lakebed_
scars=None` reproduces the EXACT prior RNG stream/outcome for any
caller without the new param; a 4000-tick LLM-disabled engine soak
with a clean round-trip (incl. legacy-snapshot backfill);
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
— pure Python, no native module touched; a live dev-server +
Playwright pass confirming the new stat tile renders and the map
canvas draws cleanly with no new JS errors.

## [1.34.49] — A19 closed: sixth spatial-memory axis + a real consumer

Explicit user instruction: "finish A19." `world/spatial_memory.py`'s
`location_character` unified 5 axes (mining/disaster/ritual/ruin/
road); this pass adds the sixth (`migration`, reading `World.
migration_trails`, M4 — the closest real existing data to the spec's
"ecology" axis) and gives the module's own long-flagged residual gap
(the `location_character(world, x, y)` World-scoped wrapper had no
caller since v1.34.1) its first real consumer.

New `spatial_memory.location_character_text()`: renders the strongest
1-2 axes of a tile's history as a plain-language clause. New
`llm/composite_entity.py` `location_history` param grounds a newly-
named place's origin story in what the SPECIFIC tile itself remembers
("this particular spot has also seen a past disaster and old mining
activity"), not just the settlement's single latest event —
`SimulationEngine._maybe_schedule_composite_entity` now computes this
via the real `World` state before building the prompt. Closes A19's
own "Feeds" checklist item ("the 'unlucky house'... places as actors,
and rich pillar perception").

Traffic/pollution/fertility remain genuinely unfolded (continuous
`FieldGrid` regions, not sparse per-tile dicts — a different shape,
real follow-up work, not attempted); ownership/construction have no
dedicated per-tile store; battles has no data source (no combat
mechanic exists, same note A18 already carries). This closes A19.

Verified: direct unit tests (`location_character_from_dicts`'s new
`migration_trails` param, backward-compat with the old positional
call shape, `location_character_text`'s strongest-2-axes ordering and
empty-history case, `composite_entity.build_prompt`'s new grounding
clause present/absent); a production-path smoke test confirming real
`World.mining_scars`/`migration_trails` state reaches the text
renderer through the actual engine; a full end-to-end test driving
`_maybe_schedule_composite_entity` with a fake LLM client, confirming
the grounding clause reaches the real prompt AND the entity registers
correctly; a 4000-tick LLM-disabled engine soak with a clean round-
trip; `scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-
identical — pure Python, no native module touched. No UI change
needed: `migration_trails` was already fully surfaced (map overlay +
inspector line) at v1.34.27; this batch is a backend-only consumer.

## [1.34.48] — Tier 0's third mirror-write -> pillar-authored site

Explicit user instruction: "Start the next one and complete as many
as you can this turn." Third conversion site: `institutions.compute_
objective`'s COUNCIL branch.

Found that this branch already had the EXACT SAME `council_
disposition` tiebreak shape v1.34.46 converted for `town_brain.
compute_priority` — unsurprising, since both read the same real
per-institution disposition signal at different decision scope.
Rather than invent a second, parallel Village-lean computation just
for this site, the SAME precomputed `village_pillar_lean` value
`SimulationEngine._village_priority_lean()` already builds is reused
here — one real question ("does the village's own accumulated sense
of itself lean toward growth or safety") asked at a second scope, not
two competing signals. Consulted only in the branch's final catchall
(no sitting council, or its own disposition came back tied); the
materials-need arm above it and any live council disposition are
never overridden. FAMILY/GUILD branches untouched — neither has an
equivalent soft/tiebreak point yet.

Verified: direct unit tests (materials-need arm never overridden;
live council_disposition never overridden; pillar lean deciding only
in the true no-signal case, in the correct direction; FAMILY/GUILD
branches unaffected by the new param); a production-path smoke test
confirming a pre-seeded Village-pillar entry reaches the real
`_maybe_schedule_institution_belief` call path through the actual
engine; a 4000-tick LLM-disabled soak with a clean round-trip;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
— pure Python, no native module touched.

## [1.34.47] — Tier 0's second mirror-write -> pillar-authored site

Explicit user instruction: "Pick the next Tier 0 site to convert."
Chose `era_branch.compute_branch` — a second pillar (Innovation, not
Village again) and the same recognizable shape v1.34.46's first site
had: a primary deterministic score that's never overridden, followed by
a previously-arbitrary tiebreak.

`compute_branch`'s tie for "which named branch (industrious/scholarly/
devout/mercantile/agrarian) does this settlement lean toward" already
favored a sticky current branch, then fell back to a bare namespaced
random pick with zero real signal behind it. New optional `pillar_
leans` param (precomputed by the caller via `Pillar.subject_
confidence` per branch name) breaks that random tie toward whichever
tied branch Innovation's own accumulated `world_model` already leans
toward — falling back to random only once genuinely no signal exists
anywhere. `SimulationEngine._maybe_schedule_era_branch` precomputes the
per-branch lean dict before calling `compute_branch`. Same self-
referential-echo-chamber avoidance as the first site: `era_branch`'s
own mirror writes a subject of `"{settlement}'s tech-path lean"`, which
never itself matches a branch-name keyword, so a settlement can't just
deterministically repeat its own last narrated lean forever.

Verified: direct unit tests (no-signal random fallback across the full
tie; sticky-branch precedence over pillar lean; a single pillar-leaning
branch winning a genuine tie; a still-tied pillar lean falling back to
random among that narrower subset; a REAL non-tied primary score never
overridden by even a maximal pillar lean); a production-path smoke test
confirming a pre-seeded Innovation-pillar entry reaches `_maybe_
schedule_era_branch`'s real tiebreak through the actual engine; a 4000-
tick LLM-disabled soak with a clean `innovation_pillar` round-trip;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.
No UI change — `settlement.era_branch` already surfaces via the
existing Era stat tile, unchanged shape.

## [1.34.46] — Tier 0's mirror-write -> pillar-authored conversion, first slice

Explicit user request: "how to go about closing Tier 0," followed by
`AskUserQuestion` answers "town_brain priority (Village)" as the first
conversion site and "design the general pattern first" as the scope.

Every Tier 0 mirror to date writes a settlement job's ALREADY-DECIDED
outcome into a pillar's `world_model`/`memory` after the fact — the
pillar observes its own history but never steers the decision. This
ships the general reusable primitive plus a first real proof site.

New `Pillar.subject_confidence(subject_substring)` (`cognition/
pillar.py`): a deterministic, zero-LLM-cost scan of this pillar's own
`world_model` (same recent-entries/substring/word-overlap match shape
`disagrees_with` already established) returning the best-matching
entry's own confidence, 0.0 if nothing matches. Any future settlement
job can fold this magnitude into an ALREADY-EXISTING soft/tiebreak
decision point — never a mechanism handing a pillar a whole decision.

First site: `town_brain.compute_priority` gained an optional `village_
pillar_lean` param, consumed ONLY at the function's existing final
catchall tie (the same place `council_disposition`'s own bounded nudge
already lives, same threshold magnitude) — every urgent arm earlier in
the function (hunger/illness/coffers/materials) is never overridden by
pillar lean, preserving v1.3.35's "just compute, highest wins, never
let the LLM override the numbers" directive exactly; the lean itself is
a plain deterministic read of already-persisted state, not a fresh LLM
opinion. `SimulationEngine._village_priority_lean()` precomputes the
value (max growth-leaning subject confidence minus max safety-leaning
one, several keyword candidates per side since a real LLM-authored
subject label is free text). Village pillar's OWN `town_brain` mirror
is deliberately excluded from ever satisfying its own lean (its subject
is `"{settlement}'s civic priority"`, which matches neither keyword
set) — no self-referential echo chamber.

Verified: direct unit tests (`subject_confidence`'s match/no-match/
best-of-several-entries behavior; `compute_priority`'s new arm firing
only past threshold, in the correct direction, and never overriding an
urgent arm); a production-path smoke test confirming `_village_
priority_lean()` reads real `village_pillar.world_model` state through
the actual engine; a real 4000-tick LLM-disabled engine soak with a
clean `village_pillar` round-trip; `scripts/verify_native_soak.py` (2
seeds x 800 ticks) byte-identical. No UI change needed — `settlement.
current_priority`/`priority_rationale` already surface through the
existing stat tile, unchanged shape.

Every other of the ~55 Tier 0 mirror sites remains write-only; docs/
ROADMAP-2026-07-REMAINING.md's Tier 0 checklist entry records this as
the first converted site, not a closed category — converting further
sites is real, un-scoped follow-up, each needing its own judgment call
about where in an existing decision a lean can safely enter.

## [1.34.45] — A18 composite reaction authoring system

Explicit user instruction: "Start A18." Ships the general authoring
system A18's own doc entry flagged as missing: a village can now
propose ITS OWN `CompositeReaction` combinations, the way `TriggerRule`
is already LLM-authored, closing the item's last open gap.

`world/reactions.py`'s `CompositeReaction` gained a real registry
shape (`id`, `hook_type`/`hook_target`/`magnitude`,
`origin_settlement_id`, `tick_created`, `status`, `fire_count`,
`last_fired_tick`; `to_dict()`/`from_dict()`) — mirroring `TriggerRule`
closely. `hook_type` is drawn straight from `world.ontology.
MECHANICAL_HOOK_TYPES`, the SAME closed vocabulary a trigger rule
uses, applied through the SAME general consumer
(`SimulationEngine._apply_trigger_rule_hook`) rather than inventing a
second effect system; the original hand-authored "Desperate Times"
keeps its own bespoke `relationship_rupture` consequence unchanged.

New `World.composite_reactions`/`next_composite_reaction_id`
(`world/state.py`, seeded via `reactions.default_composite_reactions()`,
legacy-snapshot-backfill-aware). New `llm/composite_reaction_
propose.py` (SYSTEM_PROMPT/build_prompt/fallback_propose/parse_propose,
same closed-vocabulary-hosting-open-content shape as `llm/rule_
propose.py`). New `SimulationEngine._maybe_schedule_composite_reaction_
propose`: season cadence, Village-pillar backpressure gate, deep-
reasoning LLM call, deterministic re-verification
(`reactions.validate_conditions`, never an LLM self-check), and the
SAME counterfactual-sandbox safety gate (`simulation/sandbox.py`'s
`run_counterfactual`) `rule_propose` already established — an unsafe
proposal is discarded (`composite_reaction_rejected` event), never
registered. A successfully-registered reaction mirrors into `village_
pillar.upsert_world_model()`/`remember()`, an Emergence API entry, and
a B4 Village->Reflection message arrow, same treatment `rule_propose`'s
own registration gets.

`_maybe_tick_composite_reactions`/`_apply_composite_reaction` now
operate over the real `World.composite_reactions` registry instead of
a single hardcoded reaction — `matching_reactions` gained a `reactions`
parameter (any iterable) instead of a fixed module-level tuple.

Verified: direct production-path smoke tests (fake LLM client driving
the full schedule -> sandbox -> register pipeline end to end, confirming
correct settlement/condition/hook_type on the registered reaction;
sandbox-rejection path confirmed via a forced-unsafe verdict — the
proposal is discarded and never registered); direct unit tests for
`validate_conditions`/`matching_reactions`/`register_composite_
reaction`'s cap-and-prune behavior (the world-original "Desperate
Times," `origin_settlement_id=None`, is never pruned); a real 4000-tick
LLM-disabled engine soak with a clean `World.to_dict()`/`from_dict()`
round-trip (including a legacy-snapshot-backfill check); `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical — pure
Python, no native module touched. UI: no bespoke icon needed for
`composite_reaction_originated`/`composite_reaction_rejected` — same
default-fallback-icon precedent `rule_originated`/`trigger_rule_
rejected` already established.

## [1.34.44] — A15 wildlife genetics + Tier 0 standalone checklist

Explicit user instruction: "Make a separate list in the roadmap for
just tier 0 and divide into to minimum possible steps and maximum
possible amount of work done in one turn. Start and A15 for this turn
and complete as much as possible." Two independent pieces: a docs-only
reorganization of Tier 0's existing history into a flat checklist, and
a real A15 implementation slice.

**Tier 0 standalone checklist**: `docs/ROADMAP-2026-07-REMAINING.md`
gained a new "Tier 0 — standalone checklist" subsection, a flat index
over every atomic unit Tier 0 has ever been broken into (149 numbered
steps across 8 grouped entries), with the minimum step size this
doc's own history established (one job/site mirrored, one Emergence-
tag, one attention-swap, one B4 arrow decision) and the maximum single-
turn batch actually demonstrated (14 sites, v1.34.20). Every checked
box is done as of this filing; what's left needs a fresh un-scoped
design pass (mirror-write -> pillar-authored decision), not another
item at the checklist's own size — recorded honestly rather than
inventing steps that don't exist yet.

**A15 (wildlife genetics)**: `AnimalHerd.hardiness` (0..1, 0.5
baseline, `world/wildlife.py`) — a herd/pack is already a POPULATION
aggregate, not an individual, so unlike `Agent.genome`'s diploid
two-allele system, hardiness is one continuous number representing the
population's own average constitution. Seeded with real genesis
diversity (`WildlifeGrid.generate`); on recolonization
(`_maybe_recolonize`) a new herd/pack inherits from the surviving
LOCAL gene pool's average plus mutation (founder-effect realism — a
genuine total extinction with no survivors falls back to the neutral
baseline). Real consumer: `hardiness_reproduce_factor` scales a herd's
`reproduce_chance` 0.7x-1.3x, applied in pure Python BEFORE the scalar
reaches `_native_grazer_tick_step` — zero native/index parity risk,
directly addressing the reason this item was previously deferred.
Also bridges `SpeciesVariant`'s existing descriptive-only "hardier"
trait to this real gene (`_maybe_schedule_species_variant`'s `apply()`
bumps the named herd's hardiness by `HARDINESS_VARIANT_BUMP`) — the
specific gap `SPECIES_VARIANT_TRAITS`'s own docstring flagged. UI: the
Wildlife stat tile gains a conditional "grazer/predator stock hardy/
fragile" suffix from `WildlifeGrid.summary()`'s new `avg_grazer_
hardiness`/`avg_predator_hardiness` (living herds only).

Verified: direct unit tests (`hardiness_reproduce_factor` bounds,
gene-pool inheritance centering near the pool average over 500 trials,
genesis diversity, round-trip excluding dead entries); a deterministic
threshold-crossing test of recolonization inheritance (surviving-
gene-pool bias vs. genuine-extinction baseline fallback); a direct
production-path smoke test of the SpeciesVariant bridge; a real
5000-tick LLM-disabled engine soak confirming organic hardiness
diversity + clean round-trip through the actual production path;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical;
a real dev server + Playwright pass confirming the stat tile renders
the new suffix correctly. Closes A15 for both domains this project
models heritability for (human, wildlife).

## [1.34.43] — Tier 0's Nature causal-reasoning job: last two design-note triggers

Explicit user instruction: "I thought you have closed tier 0. Please
do as many slices of if in this turn as possible" — corrected the
premise (Tier 0's own biggest lever, the ~55-scattered-LLM-job
refactor, is real progress but not closed; per-agent cognition's
volume-safe mirror WAS already closed at v1.34.34) and shipped the one
genuinely open, concretely scoped remainder: the Nature causal-
reasoning design note's other two named anomaly candidates (grazer
herd local extinction, forest succession stall), alongside the
already-shipped predator-pack extinction trigger.

`_maybe_schedule_nature_causal_reasoning` is now a thin dispatcher
over three trigger methods (`_maybe_react_to_predator_extinction` —
the original logic, extracted unchanged — `_maybe_react_to_grazer_
extinction`, `_maybe_react_to_succession_stall`), checked in that
fixed order; at most ONE schedules per tick even if more than one
anomaly happens to be live simultaneously. Grazer extinction mirrors
the predator trigger's own shape (`world.wildlife.summary()
["grazer_herds"]` crossing >0 to 0) — a real, distinct cause worth
asking about (a grazer collapse plausibly explains a LATER predator
collapse the other trigger separately reasons about). Succession
stall is genuinely different in kind — continuous, not binary: a
fallow tile in `World.fallow_ticks` whose weeks-eligible count has
reached `REFOREST_MIN_FALLOW_WEEKS * NATURE_SUCCESSION_STALL_WEEKS_
MULTIPLIER` (12 weeks at the default 3x4) despite locally favorable
moisture (`HydrologyField.at(x, y) >= NATURE_SUCCESSION_STALL_
MOISTURE_MIN`, 0.45) — taking the design note's own "despite favorable
moisture" framing literally: a tile stalled on genuinely dry ground is
skipped, not flagged, since dry ground is an obvious mundane
explanation and isn't the puzzling case worth Nature's own reasoning.
Picks the single worst-stalled QUALIFYING tile each check.

Verified: a direct production-path smoke test (fake LLM client,
extending the existing predator-extinction test's own harness)
confirming grazer extinction schedules exactly once on the falling
edge and clears on recovery; succession stall schedules for a forced
favorable-moisture stalled tile but correctly skips (without flagging)
both a dry stalled tile and a below-threshold tile; the fixed-priority
dispatcher schedules at most one job when predator+grazer+stall are
all simultaneously live (predator wins, confirmed via each flag's
post-call state); a real 5000-tick LLM-disabled engine soak (async,
real `_tick_once` loop) through the actual production path with no
regression; `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical — pure Python, no native module touched (a full
`to_dict()` equality check hit a pre-existing, unrelated set-
serialization ordering quirk in `roads.ever_established`/`river_
tiles`, confirmed present on unmodified `origin/claude/hearthmind-
overview-5bekay` too via `git stash`; verified this batch's own
fields — `fallow_ticks`, `causal_threads`, `nature_pillar.world_
model` — round-trip byte-identical instead).

This closes every named candidate in the Nature causal-reasoning
design note. Tier 0's own larger, still-open lever (extending observe/
interpret cycling, attention-budget arbitration, and inbox/outbox
messaging to the ~50 settlement-scoped LLM jobs beyond their current
one-representative-per-mechanism coverage) remains exactly as
documented — a real multi-week push, not a quick slice.

## [1.34.42] — A14 closed: sixth and final organism-biology subsystem, `sleep`

Explicit user instruction: "Finish A14," following v1.34.41's own
"Next Milestone" note. Closes A14 entirely — all six named
organism-biology subsystems (`immune_strength`, `stress`,
`injury-recovery`, `development`, `fertility`, `sleep`) are now real,
mechanically consumed state.

`Agent.sleep_debt` (0.0 = well-rested, `agents/agent.py`) is
deliberately distinct from the existing `energy` field: `energy`
already swings tick-to-tick with activity/rest, but `sleep_debt`
(`Population._tick_sleep_debt`) tracks a much SLOWER-resolving chronic
deficit — it drifts toward `1.0 - energy` via exponential smoothing at
`SLEEP_DEBT_ADAPT_RATE=0.005`, deliberately slower than `immune_
strength`'s own `IMMUNE_ADAPT_RATE=0.01` (which already tracks a
medium-term nutrition/rest reading) — a single tired tick barely moves
it; only SUSTAINED low energy across many ticks builds real debt,
matching the "history-dependence, not momentary state" shape every
other A14 subsystem established. Ticked before `_tick_immune_strength`
each tick so the same-tick reading feeds straight into its consumer.

Real consumer: `_tick_immune_strength`'s target gains a further drag
of `-sleep_debt * SLEEP_DEBT_IMMUNE_WEIGHT` (0.25), on TOP of (not
replacing) its existing momentary hunger/energy pull —
`nutrition_pull`/`rest_pull` stay untouched. "Chronic sleep
deprivation wears down the immune system in a way a single tired day
doesn't" is now mechanical, a genuinely distinct signal from the
momentary `rest_pull` already in that same target, same "modulate an
existing tuned mechanism, never replace it" discipline every A14 slice
has followed. `Agent.to_dict()`/`from_dict()` round-trip `sleep_debt`
like `stress`/`injury`/`development`.

UI surfacing (same batch): a conditional "under-rested / chronically
sleep-deprived (sleep debt N)" line in the NPC inspector's Personality
section, shown only once real debt has accumulated (no line at all
near 0, same "don't clutter with a settled fact" treatment
`injury`/`development`'s conditionals use).

Verified: direct unit tests for `_tick_sleep_debt` (drift direction,
slow convergence over many ticks, bounds, round-trip) and a
deterministic threshold-crossing test of the `_tick_immune_strength`
consumer (a zero- vs. fully-debted agent with identical hunger/energy
yielding measurably different immune_strength); a real 5000-tick
LLM-disabled engine soak (async, production `_tick_once` loop)
confirmed real, varied `sleep_debt` values formed organically through
the actual production path and the state round-trips cleanly through
`to_dict`/`from_dict`; `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical — pure Python, no native module touched; a real
dev server + Playwright pass confirmed the NPC inspector renders the
new line correctly (present and correctly labeled at a forced 0.62,
absent for a forced well-rested agent).

## [1.34.41] — A14 fourth and fifth organism-biology subsystems, `development` and `fertility`

Explicit user instruction: "Do that as well," following v1.34.40's own
"Next Milestone" note naming both remaining subsystems. Ships
`development` and `fertility`/reproduction together, closing A14 down
to only `sleep`.

A deliberate architectural split, unlike every prior A14 slice:
`development` is a genuine STORED, ticked accumulator (real state with
history-dependence, round-tripped like `stress`/`injury`); `fertility`
is a PURE DERIVED `@property` — a direct function of `age_ticks`
alone, recomputed fresh on every access, never stored, zero
round-trip surface (chronological age has no physiological lag against
itself, unlike the emotion/nutrition-driven targets `stress`/`injury`/
`immune_strength` smooth toward).

`Agent.development` (0.0 at birth, `agents/agent.py`) grows every tick
(`Population._tick_development`) at `DEVELOPMENT_GROWTH_PER_TICK`
toward 1.0 by `DEVELOPMENT_FULL_TICKS` (a bit past `MATURITY_TICKS` —
physical/cognitive growth continues into young adulthood past the age
of reproductive/social maturity), scaled 0.5x-1.2x by nutrition
(`DEVELOPMENT_NUTRITION_WEIGHT`/`_MIN_FACTOR`/`_MAX_FACTOR`) — real
childhood stunting under sustained famine, distinct from `injury`'s
acute-trauma coupling. Deliberately distinct from the existing binary
`_is_mature` gate: that gate still decides WHETHER an agent can
reproduce/work/hold office at all; `development` is a slower "how
fully grown are they" reading underneath it. A migrant
(`_maybe_welcome_migrant`) now starts at `development=1.0` (an
already-grown adult arriving from outside, not a homegrown child); a
newborn correctly inherits the 0.0 default; founders' existing
`age_ticks=0` default is self-consistent with it (left untouched, an
unrelated pre-existing quirk). Real consumer:
`Population.carrying_capacity`'s `working_age` labor term now sums
each mature/healthy adult's own `development` reading (capped 1.0,
`DEVELOPMENT_LABOR_WEIGHT`) instead of counting a flat +1 — a
chronologically-mature young adult who grew up through a hard famine
contributes measurably less labor capacity than a fully-grown peer,
even past the same binary maturity gate. "History becomes physically
visible" (CLAUDE.md's own standing design priority) applied to
demographic capacity, not just narration.

`compute_fertility(age_ticks)` is the real age-based reproductive
curve: 0 before `MATURITY_TICKS`, rises 0->1.0 over `FERTILITY_
RISE_TICKS` (2,000 ticks) after maturity, holds at 1.0 for `FERTILITY_
PLATEAU_TICKS` (8,000), then declines 1.0->`FERTILITY_FLOOR` (0.15,
never exactly 0 — "meaningful, never a hard block," matching every
other reproduction gate in the codebase) over `FERTILITY_DECLINE_
TICKS` (10,000). Absolute tick offsets from `MATURITY_TICKS`, matching
`MATURITY_TICKS`'s own convention — real reproductive decline tracks
chronological age, not an individual's own randomized eventual
lifespan. Real consumer: `Population._maybe_reproduce`'s roll is now
also scaled by the courting pair's average `fertility`
(`FERTILITY_REPRODUCTION_WEIGHT`), stacking with `stress`'s existing
psychological-drag factor on the same roll — two independent real
signals (biological readiness, psychological burden) modulating one
mechanic, not competing single-cause gates.

`Agent.to_dict()` includes `fertility` for API/broadcast reachability
only (never consumed by `from_dict` — there's no field to restore, it
recomputes fresh from `age_ticks` on every access).

UI surfacing (same batch): a conditional "still growing (development
N)" line while `development < 1.0` (nothing shown once fully grown,
same "don't clutter with a settled fact" treatment `injury`'s
uninjured case gets), and a conditional "in their prime years / past
their prime / well past childbearing years (fertility N)" line once
mature, both in the NPC inspector's Personality section.

Verified: direct unit tests for `compute_fertility` (curve shape at
every phase boundary: pre-maturity, rise-midpoint, plateau start/mid,
decline start/midpoint, floor), the `Agent.fertility` property, and
`development`'s `to_dict`/`from_dict` round-trip; a deterministic
threshold-crossing test for both real consumers (a low- vs.
fully-developed population yielding measurably different
`carrying_capacity`, and a young vs. old pair's fertility average
differing as expected); a real 5000-tick LLM-disabled engine soak
(async, production `_tick_once` loop) confirmed `development` grows
organically for real agents through the actual production path
(newborns starting near 0.0, values bounded [0,1]) and both fields
round-trip cleanly through `to_dict`/`from_dict` (`fertility`
recomputing identically from `age_ticks` on reload, as designed);
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
pure Python, no native module touched; a real dev server + Playwright
pass confirmed the NPC inspector renders both new lines correctly
(present and correctly labeled at forced values, absent for a
fully-grown/zero-fertility agent).

This closes A14 down to a single remaining named subsystem: `sleep`.

## [1.34.40] — A14 third organism-biology subsystem, `injury-recovery`

Explicit user instruction: "Continue A14," following v1.34.37's
`stress`. Predator attacks previously resolved to a flat death-or-
nothing binary — a surviving agent took an energy/hunger hit and
walked away with zero lasting trace, unlike sickness (which has
`sick_ticks` state) or the two prior A14 subsystems.

`Agent.injury` (0.0 = unhurt, `agents/agent.py`) is bumped by
`PREDATOR_ATTACK_INJURY=0.35` on `Population._maybe_predator_attack`'s
non-lethal outcome, and heals every tick (`Population._tick_injury_
recovery`) via exponential smoothing at `INJURY_RECOVERY_RATE=0.006`,
scaled 1.5x faster for a well-fed/rested agent and 0.5x for a
starving, exhausted one (`INJURY_RECOVERY_HUNGER_WEIGHT`/`_ENERGY_
WEIGHT`) — the same nutrition/rest physiology coupling `immune_
strength` already established, applied to the healing RATE instead of
a target. Real consumer: an already-injured agent surviving a FURTHER
predator attack has its kill chance scaled by `1.0 + injury *
INJURY_VULNERABILITY_WEIGHT` (0.6), capped at `INJURY_VULNERABILITY_
MAX_FACTOR` (1.6x) — applied in pure Python AFTER the existing
native-or-fallback kill-chance computation (`_native_predator_kill_
chance`), zero native/fallback parity risk, same "modulate after the
fact" pattern `stress`'s reproduction-penalty already established.

UI surfacing (same batch): a conditional "injury: healing/badly hurt"
line in the NPC inspector's Personality section, shown only once an
agent has actually been hurt (no line at all while `injury` is ~0).

Verified: direct unit tests for `_tick_injury_recovery` (round-trip,
default baseline, faster healing for well-fed/rested vs. starving/
exhausted, converges exactly to 0, no-op at 0) and a deterministic
threshold-crossing test of the predator-attack consumer (a fixed roll
landing between the base and injury-modulated kill chance, proving the
vulnerability multiplier alone flips survive to death); a real 5000-
tick LLM-disabled engine soak (async, production `_tick_once` loop)
confirmed 3 real `predator_attack` events fired through the actual
production path, injury formed and partially healed organically, and
the state round-trips cleanly through `to_dict`/`from_dict`;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
— pure Python, no native module touched; a real dev server +
Playwright pass confirmed the NPC inspector renders the injury line
correctly (present and correctly labeled at 0.62, absent for an
uninjured agent).

Reproduction and development (the spec's two remaining named
subsystems) remain open.

## [1.34.39] — A4 closed: infrastructure/information audit

Explicit user instruction: "Finish A4" (docs/ROADMAP-2026-07-
REMAINING.md's "Continuous systems vs. scripted events"), following
v1.34.38's economy slice (`scarcity`). Docs-only — no code changes;
direct code inspection found both remaining named sub-domains were
already satisfied by existing mechanisms, contrary to the item's own
stale "still fully unconverted" note.

**Infrastructure**: `RoadNetwork.tick()` (`world/roads.py`) already
gains/decays per-tile `wear` every tick (`ROAD_WEAR_PER_TICK`/`ROAD_
DECAY_PER_TICK`) — a real continuous local rule, not a discrete "build
road" event. `Settlement.tick()` (`settlement/buildings.py`) likewise
decrements `Building.condition`/`Vehicle.condition` by a per-tick decay
rate every tick. Construction/founding correctly stays a genuine
one-time event — a building coming into existence is an actual
discrete fact, same as a birth or death; A4 never asked for those to
dissolve into a field.

**Information**: gossip contagion (`Population._apply_gossip_
contagion`, shipped v1.3.6) already relaxes a listener's opinion of a
named third party toward the speaker's view every qualifying dialogue
exchange, gated by trust — a real continuous social-graph propagation
rule. `world/memetics.py`'s `weighted_spread_target` (A17) already
generalizes "who catches this next" to any content type via real
ledger closeness. `Population.spread_rumor` (a caravan's one-time news
arrival) was checked as a candidate for wiring onto `memetics.
weighted_spread_target` and found NOT to benefit: it has no existing
"carriers" at the moment of first arrival (the rumor doesn't exist in
anyone's memory yet), so weighting against zero carriers degrades to
the exact same uniform selection it already performs — a real audit
finding, not a skipped attempt.

Fixed a stale duplicate/contradictory "### A4" section left over in
docs/ROADMAP-2026-07-REMAINING.md from the v1.34.38 edit (an old
"still fully unconverted" stub sat directly above the new detailed
entry, never removed). This closes A4 entirely.

## [1.34.38] — Tier 1: A4 first slice, `scarcity` field

Explicit user instruction: "Continue with A4" (docs/ROADMAP-2026-07-
REMAINING.md's "Continuous systems vs. scripted events" item). Weather/
climate/wildlife/disasters were already continuous; agriculture
already has a real field-consumption shape via A11's `hydrology_
field.moisture` + `FarmGrid.soil_fertility`. Economy — the spec's own
literal "resource/price fields that flow" — had zero field
representation: `tick_market_prices` computes a real per-settlement
scalar (already continuous, not event-fired) but never flowed
spatially or fed anything beyond its own price multiplier.

`settlement.buildings.compute_resource_fill` factors the granary/
materials fill-ratio math out of `tick_market_prices` (behavior
unchanged) so both it and the new field can share one read instead of
duplicating the logic. New `FieldGrid.step_scarcity` (fifth `FieldGrid`
field, `world/fields.py`) sources `1 - avg(food_fill, materials_fill)`
per settlement, averages per region, then spreads via `ca_operators.
diffuse` (`SCARCITY_DIFFUSE_RATE=0.35`) — same shape every prior field
established. Real consumer: `Population._maybe_welcome_migrant`'s
chance now dampens with the settlement's own region scarcity reading
(`MIGRANT_SCARCITY_DAMPENING=0.3`, up to 30% at maximum scarcity),
same bounded shape `MIGRANT_DENSITY_DAMPENING` already established for
population density — "newcomers are less drawn to a visibly
struggling town" is now a mechanical fact, not just narration.

UI surfacing (same batch): `scarcity` is now a 7th "🗺️ fields" map
overlay mode (`interface/static/app.js`) — a green-amber-red "want"
color ramp (abundant -> struggling), legend labels, and broadcast
wiring (`interface/api.py`'s `WorldBroadcaster.set_terrain` gained a
`scarcity` param, both engine call sites updated).

Verified: direct unit tests for `FieldGrid.step_scarcity` (empty-world
all-zero, single-settlement diffusion, per-region weighted average
across settlements) and `compute_resource_fill` (neutral food-fill
default, real materials-fill reading); a deterministic threshold-
crossing test of the migrant-welcome consumer (a fixed roll landing
between the un-dampened and fully-dampened chance thresholds, proving
the multiplier alone flips welcome to no-welcome); a real 4000-tick
LLM-disabled engine soak (async, production `_tick_once` loop)
confirmed the field forms organically from real settlement economics
and round-trips cleanly through `to_dict`/`from_dict`; a real dev
server + Playwright pass confirmed all seven field modes (plus off)
cycle correctly with the right legend text and a clean render;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
pure Python, no native module touched.

Infrastructure and information (A4's other two named sub-domains)
remain fully unconverted, explicitly flagged for a future slice.

## [1.34.37] — Tier 1: A14 second organism-biology subsystem, `stress`

Explicit user instruction: "Continue as many remaining tier 1 items as
possible in this turn." First slice this turn (following v1.34.36's
`traffic`): A14's second named subsystem, `stress` — same "real
continuous state, coupled to already-real signals, modulating not
replacing an existing tuned mechanism" shape `immune_strength`
established for A14's first slice.

`Agent.stress` (0..1, `agents/agent.py`) drifts toward a target built
from already-tracked acute-threat signals via exponential smoothing
(`STRESS_ADAPT_RATE=0.03`, faster than `IMMUNE_ADAPT_RATE` — a real
stress response is a much quicker physiological reaction than immune
adaptation): current fear/grief emotions (`STRESS_FEAR_WEIGHT=0.5`/
`STRESS_GRIEF_WEIGHT=0.4`), a hunger crisis at `CRITICAL_HUNGER_
THRESHOLD` (`STRESS_HUNGER_CRISIS_PULL=0.3`), active illness
(`STRESS_SICKNESS_PULL=0.2`), and a hardened feud in `relationship_
flags` (`STRESS_FEUD_PULL=0.2`) — `Population._tick_stress`, run every
tick right after `_tick_immune_strength`. Real consumer:
`Population._maybe_reproduce`'s per-tick reproduction roll is scaled
by `1.0 - avg_stress * STRESS_REPRODUCTION_PENALTY_WEIGHT` (0.5) for
the courting pair — a fully stressed couple reproduces at half the
ordinary rate, never zero. "Chronic stress suppresses fertility" is a
real, bounded, never-dominant physiological coupling, the same scale
every other reproduction gate (affinity threshold, settlement hunger
ceiling) already uses.

UI surfacing (same batch): a plain-language "stress: at ease / on edge
/ under real strain" reading in the NPC inspector's Personality
section, right after the existing immune-constitution line
(`interface/static/app.js`).

Verified: direct unit tests for `_tick_stress` (a calm agent stays at
0, fear/grief/hunger-crisis/sickness/feud each converge to their
correct target under repeated ticks, round-trip through `to_dict`/
`from_dict`, the reproduction-penalty formula); a real 4000-tick
LLM-disabled engine soak (async, production `_tick_once` loop)
confirmed stress forms organically within real bounds and round-trips
cleanly; `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical — pure Python, no native module touched (deliberately,
same parity-safety discipline `SpeciesVariant`/A15 already flagged); a
real dev server + Playwright pass confirmed the NPC inspector renders
the new stress line with a live, real (non-zero) value.

## [1.34.36] — Tier 1: A1/A2 fourth field, `traffic`

Explicit user instruction: "Tier 1 as many slices as you can build in
this turn." Second slice this turn (following `pollution`, v1.34.35),
same "field and consumer together" shape.

`FieldGrid.step_traffic` (`world/fields.py`) sources from `World.
roads.wear` (already-real per-tile road-wear state) rather than
anything new — summed per region, normalized against the busiest
region, then spread via `ca_operators.diffuse` (`TRAFFIC_DIFFUSE_
RATE=0.3`). Real consumer: `simulation.engine._maybe_schedule_caravan`
gained a `traffic`-scaled multiplier on its monthly visit chance
(`TRAFFIC_CARAVAN_CHANCE_WEIGHT=0.5` — a fully-trafficked region draws
1.5x as often as one with none), stacking with the existing `has_
market()`/`caravan_relation_factor` multipliers already applied to
that same value — "trade follows roads" is now a mechanical fact.

UI surfacing (same batch): `traffic` is now a 6th "🗺️ fields" map
overlay mode (`interface/static/app.js`) — a cool blue-to-cyan-to-
white color ramp (deliberately outside every other mode's danger/
organic hue families, since traffic is neutral, not good or bad on its
own), legend labels ("quiet" -> "busy"), and broadcast wiring
(`interface/api.py`'s `WorldBroadcaster.set_terrain` gained a
`traffic` param, both engine call sites updated) — rides the same
weekly/terrain-change resync every other field already uses.

Verified: direct unit tests for `FieldGrid.step_traffic` (empty-world
all-zero, a lone wear source normalizes/diffuses correctly, two
different-intensity regions normalize to distinct nonzero values); a
deterministic threshold-crossing test of the caravan consumer (a fixed
roll landing between the un-boosted and boosted chance thresholds,
proving the multiplier alone flips no-visit to visit); a real 4000-
tick LLM-disabled engine soak (async, production `_tick_once` loop)
confirmed the field forms organically from real road usage and round-
trips cleanly through `to_dict`/`from_dict`; a real dev server +
Playwright pass confirmed all six field modes (plus off) cycle
correctly with the right legend text and a clean render; `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical — pure
Python, no native module touched.

## [1.34.35] — Tier 1: A1/A2 third field, `pollution`

Explicit user instruction: "Implement as many slices of tier 1 as
possible." Ships a third `FieldGrid` field (A1) with a third real
`ca_operators.diffuse` consumer (A2) in one slice, same "field and
consumer together" shape `disease_pressure` established (v1.34.24).

`FieldGrid.step_pollution` (`world/fields.py`) sources from two
already-real Body-state producers rather than anything new: standing
FACTORY/POWER_PLANT/OIL_RIG buildings (`World.POLLUTION_SOURCE_
KINDS`, `POLLUTION_BUILDING_WEIGHT=1.0`) and `World.mining_scars`
intensity (`POLLUTION_MINING_SCAR_WEIGHT=0.3`, secondary to an actual
standing factory), normalized against the region with the most, then
spread via `ca_operators.diffuse` (`POLLUTION_DIFFUSE_RATE=0.3`) —
fumes/runoff aren't confined to the exact source region. Real
consumer: `economy.farms.FarmGrid.plant()` gained a `pollution`
parameter scaling `max_yield` down to a bounded floor
(`FARM_POLLUTION_YIELD_MIN_FACTOR=0.6`, same inverse shape `moisture`'s
existing yield factor already has) — "industry chokes the fields
nearby" is now a mechanical fact, not just a name on A1's unbuilt
list. Threaded through `Population._maybe_plant` (reads `world.fields`,
already passed into `Population.tick`) and `World.tick()` (censuses
standing industrial buildings + `mining_scars` each tick, same cadence
`population_density`/`disease_pressure` already use).

UI surfacing (same batch, per the standing workflow rule): `pollution`
is now a 5th "🗺️ fields" map overlay mode (`interface/static/app.js`)
— its own color ramp (pale grey-green -> sickly olive -> smog purple-
grey, deliberately outside every other mode's red/orange hue family
since this is the one field whose story is man-made), legend labels
("clean" -> "fouled"), and broadcast wiring (`interface/api.py`'s
`WorldBroadcaster.set_terrain` gained a `pollution` param, both engine
call sites updated) — rides the same weekly/terrain-change resync
`population_density`/`disease_pressure` already use, no new channel.

Verified: direct unit tests for `FieldGrid.step_pollution` (empty-
world all-zero, a lone building source normalizes/diffuses correctly,
mining-scar-only sources contribute) and `FarmGrid.plant()`'s
pollution yield penalty (exact `FARM_POLLUTION_YIELD_MIN_FACTOR` ratio
at full pollution, unaffected default behavior when `pollution=0.0`
is omitted); a real 4000-tick LLM-disabled engine soak (async,
production `_tick_once` loop) confirmed the field forms organically
and round-trips cleanly through `to_dict`/`from_dict`; a real dev
server + Playwright pass confirmed all five field modes cycle
correctly with the right legend text and a clean render; `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical — pure
Python, no native module touched.

## [1.34.34] — Tier 0: two final slices (D11 per-agent cognition mirror, new Nature causal-reasoning job)

Explicit user instruction: "As many slice of tier 0 as you can in this
turn." Tier 0's mechanical mirror/observe-interpret/attention-budget/
inbox-outbox extension work closed fully at v1.34.20 — the two items
genuinely still open under Tier 0's umbrella were D11 (per-agent
cognition's volume-safe mirror, explicitly scoped-not-built pending a
design pick) and a scoped-but-not-built new Nature causal-reasoning
job. Both ship this pass.

**D11**: `SimulationEngine._apply_pending_cognition_results` now
mirrors a core-cast agent's goal CHANGE into `humans_pillar.memory` +
an Emergence entry — option (a) of the design note's three named
candidates. The volume gate is free: every entry reaching this loop
is already a genuine LLM-authored result (fallback never queues into
`_pending_goal_results`), and only an actual goal change (captured
via the previous goal before `apply_goal` runs) mirrors, not a same-
goal reaffirmation — far less than once/agent/day in practice. A
forced survival-override goal still mirrors (it's what really
happened), using the LLM's own reason text.

**Nature causal reasoning**: new `llm/nature_causal_reasoning.py` +
`SimulationEngine._maybe_schedule_nature_causal_reasoning` — a
genuinely NEW cognition point, not a mirror. Reactive (not cadence-
gated, same shape `skill_mastery` established): fires the tick
`world.wildlife.summary()["predator_packs"]` crosses from >0 to 0 (an
already-tracked Body-state anomaly nothing before this asked "why"
about), edge-triggered via new `_nature_predator_extinction_flagged`
(flag only latches once the job is actually SCHEDULED, so a
backpressured tick retries next tick rather than losing the anomaly).
Grounded in the specific anomaly plus real Nature Body state (predator
pressure ratio, prey scarcity, grazer herd count, disaster scars,
season). `critical=True` (a failed/budget-exhausted call defers, never
fabricates a cause); output always `status="hypothesis"`, written to
both `nature_pillar.world_model` and a new `world.ontology.
CausalThread` (`settlement_id=None`, reusing the existing dispute-
authored record shape — legible via the existing "🔗 causal threads"
panel, no new UI needed). Deliberately does not call `_pillar_close_
cycle("nature")` — this job doesn't own Nature's own observe/interpret
`cycle_stage`.

Verified: direct production-path smoke tests for both (D11: goal-
change mirrors, no-change doesn't, forced-survival-override still
mirrors with the real reason text; Nature causal reasoning: a fake-
LLM-client test driving the full trigger/schedule/apply/round-trip
path, confirming exactly-once scheduling on the falling edge, correct
`world_model`/`CausalThread`/Emergence content, and flag-clear on
recovery); a real 4000-tick LLM-disabled engine soak (async, actual
`_tick_once` loop) confirmed no regression through the production
tick path; `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical — pure Python, no native module touched.

## [1.34.33] — M6/M7: responsive-canvas redesign (closes M6/M7)

Explicit user instruction: "Implement that and do as many slices as
you can per turn" — the responsive-canvas redesign, the one item left
open in M6/M7 after v1.34.30-.32 shipped legends/gradients/hotspots/
thresholds. Closes M6/M7 and "The Living Map" (Tier 1.5) entirely.

The map's drawing BUFFER (`canvas.width`/`.height`, world pixels =
tiles * `CELL`) stays untouched as the one true coordinate system —
every existing draw call and the `view` zoom/pan transform still key
off it exactly as before. Only the element's CSS DISPLAY size is new:
`resizeCanvasDisplay()` fits it to the actual viewport (`window.
innerWidth/innerHeight` minus the panel's own offset and a margin),
bounded `[MAP_DISPLAY_MIN_SCALE=0.3, MAP_DISPLAY_MAX_SCALE=1.5]` of
the buffer so a large map never forces page scroll and a small map
never sits as a tiny fixed block regardless of window size — the
actual problem M10 (v1.34.29) could only partially address by raising
`CELL`. Wired at the end of `drawStaticTerrain()` (every buffer-size
change: initial load, era changes, terrain resync) and a debounced
`window.resize` listener (`requestAnimationFrame`-throttled).

Mouse-event math needed a matching fix wherever CSS display size can
now diverge from buffer size: new `canvasEventPoint(ev)` returns both
raw CSS-pixel offsets (for tooltip positioning, which tracks the
cursor in screen space) and buffer-scaled offsets (for `screenToGrid`/
zoom-around-cursor math, which operate in the buffer's world-pixel
space) — same pattern the relationship-graph canvas's hover handler
already established (`scale = relCanvas.width / rect.width`), applied
here to `wheel`/`mousemove`/`click`. Drag-pan's `dx`/`dy` (CSS pixels)
now also scale by the same factor before being added to `view.x`/`.y`
(buffer pixels), so a drag stays pinned to the cursor at any display
scale. `#map-panel` (`flex: 0 0 auto`) auto-tracks the new canvas CSS
size with no separate panel-sizing code; the minimap (fraction-based
click math) and season-vignette (`inset: 8px`, tracks the panel)
overlays needed no changes.

Verified: `node --check` clean; a real dev server + Playwright pass
across three viewport sizes (1800x1000, 900x700, 640x900) confirmed
the canvas CSS size actually tracks the viewport in each case and
click-to-tile-inspector opens correctly; a dedicated click-accuracy
test clicked a known fractional canvas position at a 880px-CSS/768px-
buffer (1.15x) scale and got the exact expected tile coordinate; a
zoom+pan+click sequence (6 wheel notches, a 120x80px drag, then a
click) confirmed `view.scale`/`view.x`/`.y` update sensibly and the
final click still resolves to a valid in-bounds tile — no drift from
the buffer/display scale correction.

## [1.34.32] — M6/M7: field-overlay threshold contours

Explicit user instruction: "Continue that" — the "thresholds" quarter
of M6/M7's four-part ask (docs/ROADMAP-2026-07-REMAINING.md, Tier
1.5), left open by v1.34.31's gradients+hotspots slice.

Audited all four field overlay modes against their real backend-
consumed constants before drawing anything, per the project's standing
"never draw a meaningless mark" discipline: `economy.farms.
SOIL_FERTILITY_MIN` is an asymptotic floor the depletion math can
approach but never cross, not a decision boundary; `agents.population.
MIGRANT_DENSITY_DAMPENING`/`OUTBREAK_DISEASE_PRESSURE_WEIGHT` are both
continuous multipliers applied smoothly across the whole 0..1 domain,
no qualitative cutoff. Moisture is the one mode with a genuine
two-sided mechanical threshold: `world.hydrology.WETLAND_FORM_
MOISTURE_THRESHOLD` (0.75) — a tile sustained above this line can
convert GRASSLAND to `Biome.WETLAND` (M4's `tick_wetlands`, already
shipped this session), a real different biome, not cosmetic.

New `drawFieldContour(grid, threshold, color)` (interface/static/
app.js): traces a real isoline via per-cell right/bottom neighbor
threshold-crossing detection — a lightweight edge-crossing tracer
sufficient at this map's tile resolution, not a full marching-squares
implementation. Wired only into the moisture branch of `renderField
Overlay()`. `#field-legend` gains a matching "wetland-forming
threshold (0.75)" readout line, shown only in moisture mode — deli-
berately not fabricated for the other three modes, which have no real
threshold to show.

Verified: `node --check` clean; a real dev server + Playwright pass
confirmed the legend threshold line renders correctly only in moisture
mode (hidden in soil_fertility/population_density/disease_pressure)
and the contour traces visibly on the live moisture map with no
rendering regression to v1.34.31's gradients/hotspots.

## [1.34.31] — M6/M7: field-overlay gradients + hotspots

Explicit user instruction: "Continue larger remaining scope" — the
larger, explicitly-flagged rest of M6/M7 (docs/ROADMAP-2026-07-
REMAINING.md, Tier 1.5) left open by v1.34.30's legend-only slice.
Ships two of the doc's remaining three asks ("gradients, hotspots,
thresholds" against Cities: Skylines/Timberborn/Dwarf Fortress
conventions) in one pass since they share the same underlying data
structure; "thresholds" (contour-line banding) and a full responsive-
canvas redesign remain the still-open rest.

**Gradients**: `FIELD_COLOR_STOPS` (interface/static/app.js) replaces
each of the four field modes' flat single-hue alpha ramp with a real
3-stop RGB-interpolated gradient (`lerpColorStops`) — moisture goes
tan (dry) -> green -> saturated blue; soil fertility goes red-amber
(depleted) -> neutral tan -> rich green, genuinely centered on the
real 0.5 midpoint rather than two independent alpha ramps meeting at
a hard edge; population density and disease pressure both get
conventional pale-to-orange-to-red heat ramps (distinct hue families
from each other, same discipline the flat-alpha version already had).
`paintFieldCell` is the one shared paint helper all four branches of
`renderFieldOverlay` now call, replacing four near-duplicate inline
`fillStyle` computations.

**Hotspots**: each render pass now tracks the field's own genuine
peak cell/region while painting (soil fertility tracks whichever
value is furthest from the real 0.5 neutral point, not the raw
maximum, since a notable LOW reads as a real signal too) and, once
painting finishes, draws a real marker (`paintFieldHotspot`, a white
ring + center dot) directly on the map at that position —
`FIELD_HOTSPOT_MIN_VALUE=0.12` floors this so an all-empty field
(e.g. disease_pressure before any outbreak has ever occurred) doesn't
get a meaningless marker on its technically-nonzero minimum cell.

**Legend stays honest by construction**: `FIELD_LEGEND_LABELS` now
holds only the plain-language min/max labels — the gradient bar
itself is generated live via `stopsToCssGradient(FIELD_COLOR_STOPS[
mode])` in `updateFieldLegend()`, reading the exact same array
`renderFieldOverlay` paints from, so legend and overlay can never
silently drift apart the way two independently-hand-written color
strings eventually would. A new `#field-legend-peak` line surfaces
the live hotspot coordinate when one exists.

Verified: a real dev server + Playwright pass across all four modes —
confirmed the tan-green-blue moisture gradient and the bidirectional
red-tan-green fertility gradient render correctly, confirmed a real
hotspot ring appears on a genuinely-saturated moisture tile with a
matching "hotspot at (x, y)" legend line, and confirmed soil fertility
correctly shows NO hotspot on a fresh, entirely-unfarmed map (nothing
clears `FIELD_HOTSPOT_MIN_VALUE` yet) rather than a spurious marker.
Frontend-only change, no backend/native-soak surface touched.

## [1.34.30] — M6/M7: field-overlay legend ("The Living Map," Tier 1.5)

Explicit user instruction: "Continue" — M6/M7 (docs/ROADMAP-2026-07-
REMAINING.md, Tier 1.5), the last item open in "The Living Map" after
M1/M9, M4, and M10 all closed this session. The doc's own four-part
ask for the "🗺️ fields" overlay (moisture/soil fertility/population
density/disease pressure) is "gradients, hotspots, thresholds,
legends" against reference-game conventions (Cities: Skylines/
Workers & Resources/Timberborn/Dwarf Fortress) — a genuine UI
redesign item, explicitly larger than a single pass. This ships the
"legends" quarter only, the smallest coherent, self-contained,
frontend-only slice: today's overlay had literally no legend — a
color alone never told a player whether they were looking at 0.3 or
0.7, or even which direction was good.

New `#field-legend` (`interface/index.html`/`style.css`/`app.js`):
shown only while a field overlay mode is active, mirroring each
mode's real `renderFieldOverlay` color mapping exactly rather than a
generic scale — a gradient swatch plus plain-language low/high labels
answering the actual gameplay question each mode exists for ("where
can I farm?" -> soil fertility's "depleted -> rich", not "0.0 -> 1.0").
`updateFieldLegend()` runs on every toggle click, one new small
function, no change to the existing four color-mapping branches.

Real collision caught during verification, not assumed: the legend's
first placement (bottom-left, mirroring the minimap's bottom-right)
collided with `#consequences-strip`'s existing home in that exact
corner — a real Playwright screenshot showed the overlap before it
shipped. Repositioned to stack above `#minimap` (same right edge,
`bottom: 168px`) instead.

Verified: a real dev server + Playwright end-to-end pass — clicked
through all four overlay modes, confirmed the legend shows/hides
correctly and each mode's title/min/max labels match the design, then
screenshotted all four (soil moisture and soil fertility visually
inspected directly, confirming the bidirectional amber-to-green
fertility gradient renders correctly and no longer overlaps the event
banner).

This is the "legends" piece only — true multi-stop gradients (today's
overlays are still flat per-tile alpha, not smoothed), hotspot
markers, and a full reference-game-quality responsive-canvas redesign
remain the larger, still-open rest of M6/M7, not attempted this pass.
With M1/M9, M4, M10, and this legend slice all shipped, Tier 1.5 "The
Living Map" has no fully-unaddressed item left — only M6/M7's larger
remaining scope, explicitly flagged rather than silently dropped.

## [1.34.29] — M10: base map readability ("The Living Map," Tier 1.5)

Explicit user instruction: "Continue" — M10 (docs/ROADMAP-2026-07-
REMAINING.md, Tier 1.5), the roadmap's own flagged item: "whether the
BASE map (every overlay off) already reads as alive... needs a direct
look before scoping a fix." Took that direct look this pass: launched
a real dev server (`--llm-disabled`, so no external LLM dependency),
let a real world tick forward ~2400 ticks, and screenshotted the
default UI (no overlays toggled) via Playwright.

The real finding: at the old `CELL=8`, the default 64x64-tile world's
map canvas rendered as a fixed 512x512px element — a small corner of
any real browser window, with no responsive resizing. This directly
contradicts CLAUDE.md's own standing Observatory UI direction ("the
map is the primary interface, read at a glance like an observatory
instrument... prefer overlays... over sidebar panels") — the base map
did not read that way; it read as a small inset next to a dominant
sidebar.

Fixed the one safe, self-contained lever available without touching
the zoom/pan coordinate system (`view.scale`, `screenToGrid`) or
building real viewport-responsive resize handling: `CELL` raised from
8 to 12 (interface/static/app.js). Every draw call and every mouse-
position calculation in the file already derives from this single
constant, so the change is uniform and low-risk — no coordinate-system
rewrite, no backend touch.

Verified: a before/after screenshot pair confirming the map now
visibly dominates the layout; a real Playwright click test (clicked a
known screen position, confirmed it resolved to the correct tile
coordinate — (19, 19) — and the tile inspector opened with real
content, including a live migration-trail reading, confirming v1.34.27's
M4 mechanism is genuinely visible in the running UI); a zoom test
(mousewheel zoom, hover tooltip, and minimap viewport rectangle all
still track correctly post-change). A full responsive canvas (resize-
to-viewport, gradients/hotspots/thresholds/legends matching reference-
game conventions) is explicitly flagged as the larger, still-open M6/
M7 UI redesign item — this is the smallest coherent step in that
direction, not a substitute for it. With M1/M9, M4, and M10 all closed
this batch, only M6/M7 remains open in Tier 1.5 "The Living Map."

## [1.34.28] — M4: wetlands (closes "The Living Map," Tier 1.5's M4)

Explicit user instruction: "Continue" — the wetland/marsh half of M4,
flagged open in v1.34.27's own entry: "hydrology drives moisture
today, not a distinct expanding/shrinking biome."

New `Biome.WETLAND`, appended LAST in the enum's declaration order
(not inserted between existing members) — the native `TerrainGrid`
storage backend encodes biome as an int index into `tuple(Biome)`, so
a new member must only ever append, never insert, or every already-
persisted native-backed snapshot's biome indices would silently shift.
`world/hydrology.py`'s new `tick_wetlands` (monthly, same cadence as
river re-carving): a GRASSLAND tile whose surface moisture AND
groundwater both stay near-saturated for `WETLAND_FORM_MONTHS_
REQUIRED=6` CONSECUTIVE months (progress resets to absent, not just
paused, the moment either drops below threshold — same "sustained,
not merely accumulated" discipline as the scar-shaped dicts) converts
to WETLAND; an existing WETLAND tile reverts to GRASSLAND once
moisture falls below a deliberately lower `WETLAND_DRY_MOISTURE_
THRESHOLD` (hysteresis, so a wetland doesn't form-and-dry within one
season's normal swings). Never touches a developed tile in either
direction (`_is_developed`, same discipline `recarve_rivers`/`apply_
climate_drift` already apply). New `World.wetland_progress` (self-
bounded like `fallow_ticks`) tracks the streak.

Real consequence needed no bespoke consumer (a genuine biome value,
unlike a scar-shaped overlay dict, already flows into every existing
biome-gated system): `Biome.WETLAND` is deliberately in neither
`agents/population.py`'s `WALKABLE_BIOMES` nor `economy/farms.py`'s
`FARMABLE_BIOMES` — a formed wetland is an immediate, real constraint
on routine agent movement and farm siting, same class of consequence
as any other terrain reclassification. `world/terrain_evolution.py`'s
`_skip_climate_drift` extended to also skip WETLAND (same reason it
already skips RIVER — neither has a `BIOME_ORDER` entry, since neither
is elevation-classified).

UI: new "Wetlands" main-UI stat tile (reads the existing `biome_
counts.wetland` the broadcast payload already carries — no new field
needed there), a distinct map fill color, `wetland_formed`/`wetland_
dried` life-event categories wired into `TERRAIN_CHANGING_CATEGORIES`
(both Python and JS) for the map resync, `CATEGORY_META`/`EVENT_GROUP_
OF` entries.

Verified: direct smoke tests (formation only after the full required
streak, an interrupted streak genuinely resets rather than pausing,
reversion on drying, developed-tile protection); a `WALKABLE_BIOMES`/
`FARMABLE_BIOMES` exclusion check; a real `World.create_new`/`tick()`
production-path test (temporarily lowered thresholds/months to force
formation within budget) confirming wetlands form end-to-end with a
clean `to_dict`/`from_dict` round-trip (including legacy-snapshot
backfill of `wetland_progress` to `{}`); a separate unmodified-
defaults 4000-tick soak confirming no crash at real production
thresholds; `scripts/verify_native_soak.py` (2 seeds x 800 ticks, and
again after the `_skip_climate_drift` change) byte-identical — the new
Biome member and its native int-index mapping are exercised by every
existing soak run, not just a dedicated toggle, since `_BIOME_LIST`/
`_BIOME_TO_INDEX` are derived automatically from the enum. This closes
M4 and, with it, every item explicitly scoped for Tier 1.5 "The Living
Map" this pass (M1/M9 and M4) — M6/M7 (UI redesign) and M10 (base-map
readability audit) remain open, not attempted.

## [1.34.27] — M4: wildlife migration trails ("The Living Map," Tier 1.5)

Explicit user instruction: "Continue" — following directly off
v1.34.26's own M1/M9 slice, the natural next Tier 1.5 item per the
roadmap's own note: M4's migration-trail accumulator is "same shape as
`ritual_activity`, different trigger — real reuse opportunity."

New `terrain_evolution.apply_migration_trail`/`decay_migration_trails`
(`MIGRATION_TRAIL_GAIN_PER_STEP=0.08`, `MIGRATION_TRAIL_DECAY_PER_
WEEK=0.02`, ~9 weeks to clear — fainter and faster-fading than a road
scar, since one herd's single pass is a much weaker mark than agent
traffic) + `World.migration_trails`, the 6th scar-shaped dict. Gained
via `WildlifeGrid.tick`'s new optional `migration_trails` param
(`None` reproduces the exact pre-M4 RNG stream and behavior — verified
byte-identical): a GRAZER herd that actually moves this tick leaves a
mark at its new position.

Real consequence is a genuine feedback loop, not a one-way downstream
consumer (the A9 "no write-only producers" discipline, satisfied
differently than the other five scar dicts): when a GRAZER chooses
among its move candidates, it weights toward a tile with existing
trail intensity (`wildlife.MIGRATION_TRAIL_PREFERENCE_WEIGHT=3.0`) —
herds genuinely tend to reuse the same crossings, so the trail-forming
mechanism and its own consumer are the same code path. Scoped to
GRAZER only, per the vision doc's own "grazing patterns" framing —
predators track prey, not paths.

UI: new "Migration trails" main-UI stat tile, a faint worn-path map
overlay (`paintMigrationTrails`, a distinct green-brown tone from
`paintRoadScars`' worn-earth — animal traffic reads differently from
civilization's), a bare-tile inspector line. No dedicated life-event
category — migration trails accumulate across many roaming tiles
rather than a few discrete sites (unlike mining/road, where a
threshold-crossing event is a rare, meaningful occurrence), so this
rides the existing 20s periodic `/terrain` refetch (the same channel
moisture/soil_fertility/population_density already use) rather than
adding to `TERRAIN_CHANGING_CATEGORIES`.

Verified: direct smoke tests (`apply_migration_trail`/`decay_
migration_trails` gain/cap/decay); a real `WildlifeGrid.tick()` test
over 500 ticks confirming trails form from actual grazer movement
through the production call path; a parity test confirming `migration_
trails=None` (the default) reproduces byte-identical herd position/
count against the pre-M4 code path over 300 ticks (same RNG stream,
zero behavior change for existing worlds); a real `World.create_new`/
`World.tick()` production-path test (4000 ticks) confirming trails
form end-to-end with a clean `to_dict`/`from_dict` round-trip
(including legacy-snapshot backfill to `{}`); `scripts/verify_native_
soak.py` (2 seeds x 800 ticks, and again after the broadcast-layer
changes) byte-identical — pure Python, no native module touched.

## [1.34.26] — M1/M9: old road beds ("The Living Map," Tier 1.5)

Explicit user instruction: "Continue tier 1.5" — M1/M9 (docs/ROADMAP-
2026-07-REMAINING.md, Tier 1.5, docs/VISION-2026-07-24-LIVINGMAP.md),
the roadmap's own flagged gap: a fully-decayed ESTABLISHED road
(`RoadNetwork.wear` reaching zero) was simply deleted from `self.wear`
with no persistent trace — unlike mining/disaster/ritual/ruin, which
all leave a real, slowly-decaying mark. Confirmed real via direct code
read before starting.

New `RoadNetwork.ever_established` (`world/roads.py`): tracks every
position that has crossed `ROAD_ESTABLISHED_WEAR` at least once,
independent of current wear — needed because `wear` alone can't
distinguish "a real abandoned road" from "a tile that saw a few
passing footsteps and faded without ever becoming a path." `tick()`
now returns the list of positions abandoned THIS tick (only ones that
were genuinely established), instead of `None`.

New `terrain_evolution.apply_road_scar`/`decay_road_scars` (`ROAD_
SCAR_GAIN_ON_ABANDONMENT=0.4`, `ROAD_SCAR_DECAY_PER_WEEK=0.008`, ~1
year to fully clear) — same shape as `ruin_scars`, smaller gain/faster
decay since a road bed is a fainter mark than a razed building.
`World.road_scars` (new field, same additive-overlay-dict pattern),
gained via `Population._update_roads` (now returns a real
`road_scarred` life event) each time `roads.tick()` reports an
abandonment, decayed weekly in `World._tick_terrain`'s existing
`week_end` block.

Real consumer (A9 "no write-only producers" discipline): `world/
spatial_memory.py`'s `location_character`/`location_character_from_
dicts` gained a 5th axis (`"road"`); `Population._choose_build_site`
applies `ROAD_SCAR_SITE_BONUS_SCALE=0.3` (smaller than ruin's 0.6) to
a tile with a prior old road bed — "the village rebuilds along its own
old travel corridors," the same formation-to-consumption callback loop
`ruin_scars` already has.

UI: new "Old roads" main-UI stat tile, a faint worn-earth map overlay
(`paintRoadScars`, distinct from both a standing road's own drawn line
and `paintRuinScars`' stone tint), a bare-tile inspector line,
`road_scarred` added to `TERRAIN_CHANGING_CATEGORIES` (both Python and
JS) and `CATEGORY_META`/`EVENT_GROUP_OF`. `WorldBroadcaster.set_terrain`
gained a `road_scars` parameter, wired at both call sites in
`simulation/engine.py`.

Verified: direct smoke tests (establish-then-abandon produces a scar
only for a genuinely-established road, a briefly-visited tile does
NOT scar, weekly decay clears it, `RoadNetwork`/`World` round-trip
including legacy backfill for both `ever_established`, a `spatial_
memory` unit check); a real production-path test through `World.
create_new`/`World.tick()` (temporarily raised wear-gain/decay rates
to force establishment and abandonment within the test's tick budget)
confirmed `road_scarred` events fire and `World.road_scars` populates
through the actual engine tick loop, with a clean `to_dict`/`from_dict`
round-trip; `scripts/verify_native_soak.py` (2 seeds x 800 ticks, plus
a follow-up 2 seeds x 400 after the `engine.py`/`api.py` broadcast
changes) byte-identical — no native module touched, this is pure
Python.

## [1.34.25] — A3: rivers re-carving their course via erosion

Explicit user instruction: "Continue roadmap" — A3 (docs/ROADMAP-2026-
07-REMAINING.md, Tier 2 item 5), unblocked now that A11's erosion
(v1.34.23) made `Tile.elevation` a real, actively-written value rather
than a static one.

Rivers were carved once at world genesis (`hydrology.generate_
rivers`) by steepest-descent from a handful of high-elevation sources,
then left static — the module's own docstring said as much. Since
erosion now genuinely reshapes elevation over real time, a river's
actual course should genuinely reshape with it.

New `hydrology.river_sources_used(seed, terrain)`: the exact
deterministic source-position list `generate_rivers` carves from,
factored out so it can be captured ONCE at genesis (`World.river_
sources`) and reused for every future re-carve — re-deriving sources
from current terrain later would drift if erosion has since changed
the biome at a source position, so this persists the ORIGIN points,
not the terrain reading that chose them.

New `hydrology.recarve_rivers(sources, terrain, river_tiles_before,
settlements, farms, excluded)`: re-walks each source by the identical
steepest-descent rule against CURRENT elevation. A tile the new walk
no longer visits reverts to whatever biome its current elevation
actually classifies as (`classify_with_bias`) — a river that's moved
on leaves dry former riverbed behind, not lingering phantom water. A
newly-visited tile becomes `Biome.RIVER`. Never touches a developed
tile (standing building/vehicle/farm) in either direction — same
`_is_developed` discipline `apply_climate_drift` already applies
(imported directly from `terrain_evolution.py`, no circular-import
risk); a developed tile that would otherwise revert instead just
stays classified as river, since no mechanic exists to un-found a
building the river moved away from.

Wired into `World._tick_terrain`'s `month_end` block, right after
climate drift — monthly, since erosion itself only moves a capped
amount per WEEK, so re-walking more often would mostly just reconfirm
the same course. New `World.river_tiles`/`river_sources` persisted
state (both captured at genesis in `create_new`, backfilled on legacy
snapshots — either re-derived from a pre-A3 save that already has
`lakes`/`Biome.RIVER` tiles carved, or generated fresh alongside lakes
for a truly pre-hydrology-pass snapshot, neither path a narrated
migration event since this is background bookkeeping). New `World.
river_tiles_shifted_total` counter, `river_recarved` event category
(added to `TERRAIN_CHANGING_CATEGORIES` so the client map resyncs).
UI: the existing "Erosion" stat tile extended to also report riverbed
shift count.

Verified: `ast.parse()`/`node --check` clean; direct smoke tests —
recarving unchanged terrain reproduces the identical river tiles
byte-for-byte (determinism), a genuine elevation reshape shifts the
course to different tiles while correctly reclassifying abandoned
tiles away from `Biome.RIVER`, a dramatic elevation drop redirects a
river straight into new standing water (a real, correct terminal
case, not a bug — caught during test design when an overly aggressive
first test edit produced an empty result and needed to be understood
before being called a failure), a developed tile is never reverted
even when excluded, and re-running against an already-stable course
is a genuine no-op; a real 4000-tick engine run confirmed both
`river_tiles`/`river_sources` persist correctly through a full
`World.to_dict`/`from_dict` round-trip via the actual production tick
path; both legacy-backfill branches (a snapshot with `lakes` already
present, and a fully pre-hydrology-pass snapshot without `lakes`
either) tested directly and confirmed to derive sensible state without
crashing; `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical — no native module touched, same as A11.

This closes A3. Settlements/cultures still evolving via LLM rather
than deterministic procgen remains open, flagged in the item's own
roadmap entry as an arguably-correct design question, not a gap.

## [1.34.24] — A1/A2: disease_pressure field + its diffusion consumer

Explicit user instruction: "Start A1 and A2" — docs/ROADMAP-2026-07-
REMAINING.md's Tier 1 items 3-4. Both had exactly one real
consumer/field before this pass (`population_density` for A1,
forest succession for A2); this ships their SECOND real slice
together, deliberately as one unit rather than two separate passes,
because the natural second field for A1 and the natural second
consumer for A2 turned out to be the same mechanism.

**`disease_pressure`** (`world/fields.py`'s `FieldGrid.step_disease_
pressure`): recomputes a raw regional sick-fraction census each tick
(same "live census, not accumulating" shape `population_density`
already established), then spreads it into neighboring regions via
`world/ca_operators.py`'s `diffuse` — contagion risk is a regional
property, not confined to the exact region sick agents currently
stand in, which is the whole point of using a diffusion operator here
rather than a bare census. `DISEASE_PRESSURE_DIFFUSE_RATE=0.35`
governs how strongly it spreads.

Real consumer: `Population._maybe_outbreak`'s index-case draw
(previously a flat `rng.choice(healthy)`) now weights each healthy
agent by their own region's `disease_pressure` via `new OUTBREAK_
DISEASE_PRESSURE_WEIGHT=4.0` constant — `weight = 1.0 + pressure *
4.0`, applied with `rng.choices(..., weights=...)`. A region bordering
a real outbreak becomes measurably more likely to seed the NEXT
spontaneous case than one nowhere near any sickness, without ever
excluding any healthy agent outright (every region keeps a real floor
weight of 1.0). This changes WHO an outbreak roll picks once it
already succeeded — never whether or how often an outbreak fires;
that stays exactly as tuned by the existing crowding/road-contact
multipliers.

`Population.tick`'s existing `fields` param (already threaded through
for `population_density`) now also reaches `_maybe_outbreak` via a new
`map_size` param; `World._tick_disasters` calls `step_disease_
pressure` right after `step_population_density`, same one-tick-stale
read pattern `population_density`'s own consumer already has (the
field for THIS tick reflects last tick's write). UI: `disease_
pressure` added as a fourth mode on the existing "🗺️ fields" map
overlay toggle (sickly yellow-green, distinct from population
density's pink) and threaded through `WorldBroadcaster.set_terrain`/
`GET /terrain`.

Verified: `ast.parse()`/`node --check` clean; direct smoke tests
(diffusion spreads outward from a forced sick cluster into orthogonal
neighbor regions while the source stays highest, empty world stays
all-zero); a real weighted-distribution test (20,000 forced-success
outbreak rolls with a real `random.Random`, not a rigged one — a
first attempt using a mocked always-return-0 RNG produced a degenerate
100%-vs-0% result and was caught and redone properly) confirmed the
region weighted 5x more likely to be the source of pressure was
picked ~4.97x more often than the zero-pressure region, matching the
designed 5.0-vs-1.0 weight ratio almost exactly; a real 200+-tick
engine run with agents forced sick mid-run confirmed the field
populates through the actual production tick path, not just the
isolated function; a 4000-tick engine run (LLM disabled) confirmed a
clean full-`World` round-trip; `scripts/verify_native_soak.py` (2
seeds x 800 ticks) byte-identical — no native module touched.

## [1.34.23] — A11: groundwater + erosion (continuous hydrology, second slice)

Explicit user instruction: "Start next roadmap item" — A11 "Continuous
hydrology" (docs/ROADMAP-2026-07-REMAINING.md, Tier 1 item 2), the
roadmap's own highest-leverage remaining item: it blocks A3's rivers-
re-carving and several Tier 1.5 "Living Map" items, all gated on
`Tile.elevation` becoming mutable. First slice (surface moisture flow)
shipped v1.13.0; this ships the two pieces that slice explicitly
flagged unbuilt.

**Groundwater**: new per-tile `HydrologyField.groundwater` reservoir,
distinct from surface `moisture`. Wet land (`moisture` above a
threshold) infiltrates a fraction into groundwater each week; dry land
seeps a fraction back out — a real base-flow/spring effect where land
that was recently wet resists drying out faster than land that never
was, even at an identical surface reading right now. A small constant
weekly percolation loss keeps it from ratcheting upward forever.

**Erosion**: research first — `Tile.elevation` turned out to already
be storage-layer mutable on both the native `TerrainGrid` and the
Python fallback since v0.74.1 (`TerrainGrid._set_tile`/`TerrainRow.
__setitem__` already accepted and stored any elevation value; every
existing mutator just always echoed the unchanged value back). New
`tick_erosion` is the first real writer of a genuinely new elevation
value: reuses `tick_hydrology`'s own steepest-descent neighbor search
— a tile whose surface moisture clears `EROSION_MOISTURE_THRESHOLD`
(genuinely carrying flow, not just damp) moves a small, capped,
mass-conserving fraction of its elevation excess to its lowest
orthogonal neighbor, skipping any tile whose lowest neighbor is a
pinned water/RIVER biome (siltation into standing water stays out of
scope, flagged). Whenever a tile's elevation crosses a real biome
threshold, `classify_with_bias` re-derives its biome in the same
write — the one real coherence hazard, since nothing else in the
codebase reads raw `.elevation` (everything keys off `.biome`).

Weekly cadence, called right after `tick_hydrology` in `World.
_tick_disasters` (both read that week's freshly-updated moisture).
R7 deviation carried forward from `hydrology_field.py`'s existing
docstring (pure Python, not yet natively ported — same "prove the
shape live before compiling it" justification as the first slice);
erosion's elevation writes go through the exact `TerrainGrid` storage
API every other terrain mutator already uses, so this adds no new
native-vs-fallback equivalence risk beyond what those modules already
carry.

New `terrain_eroded` event category (added to `TERRAIN_CHANGING_
CATEGORIES` so the client map resyncs on a real erosion-driven biome
change), a monotonic `World.tiles_eroded_total` counter, `summary()`'s
`hydrology` block gained `avg_groundwater`/`tiles_eroded_recorded`.
UI: "Soil moisture" stat tile extended to show groundwater alongside
surface moisture; new "Erosion" stat tile.

Verified: `ast.parse()`/`node --check` clean; direct smoke tests —
sustained erosion smooths an artificial elevation gradient while
exactly conserving total elevation mass over 400 simulated weeks,
groundwater/moisture stay bounded [0,1] over 200 alternating wet/dry
weeks, flat terrain produces zero erosion (no downhill neighbor),
`to_dict`/`from_dict` round-trips exactly, a legacy pre-groundwater
snapshot backfills at the default; a real 3000-tick engine run (LLM
disabled) through `SimulationEngine._tick_once` confirmed both
mechanisms fire through the actual production path (28 tiles eroded
in that run) with a clean full-`World` round-trip;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

This closes A11. A3's river-re-carving and Tier 1.5's M2/M8 (real
erosion/flooding-reshapes-terrain map representation) are now
unblocked but not yet attempted — recorded as the natural next step
in docs/ROADMAP-2026-07-REMAINING.md, not queued or auto-chained per
this project's standing convention.

## [1.34.22] — D6: Districts (collective NPCs at scale)

Explicit user instruction: "For D6 at some number of villagers as
threshold promote them to collective NPCs instead of single NPCs.
These can be districts, smaller towns or something like that. Take
hints from the doc itself" — implements D6 (docs/ROADMAP-2026-07-
REMAINING.md, filed scoped-not-built in v1.34.21), the last open Tier
0.5 item.

D6's diagnosed problem: every `Agent` carries an O(population) social
surface via the pairwise `Ledger` (`agents/ledger.py`) — relationships/
trust/debts/relationship_flags/grievances dicts keyed by any other
living agent's id, with no locality bound. Realistic at a few hundred,
implausible at a thousand+.

**New `hearthmind/settlement/district.py`**: once a settlement's
individually-simulated NON-core population crosses `DISTRICT_
INDIVIDUAL_CAP=250`, the least-prominent excess (`Population.
_prominence`, ascending) is genuinely removed from `Population.agents`
and the native `AgentStore` (when present) AND from every surviving
agent's `Ledger` entry for them — the same per-survivor cleanup
`_apply_deaths` established (v0.42.0), deliberately NOT reused
directly since collectivization skips grief/memorial/inheritance (no
one died) — and folded into a `District`'s aggregate population
instead. This is the actual fix: a collectivized person no longer has
a `Ledger` entry anyone can hold, which is what bounds the social
surface, not a cosmetic population count. `DISTRICT_MAX_
POPULATION=150` caps a single district before a new one spins up — the
"smaller towns" half of the directive: growth past a district's cap
reads as a new named ward ("North Ward", "Millgate", ...; fully
procedural, zero LLM cost, 12-name pool cycling with a numeric suffix),
not one unbounded blob. Core-cast agents and any living MAYOR are never
candidates — same "named cast stays named" boundary `core_agent_ids`
already draws for LLM budget, applied here to identity/social-surface
scaling instead.

A `District` is deliberately NOT a named character or an `Institution`
— no beliefs, no cognition, no LLM authorship. Closer to `FarmGrid`/
`WildlifeGrid`: a cheap deterministic aggregate, ticked daily
(`day_end`, `Population.tick_districts` -> `district.tick_district`)
with its own fractional-accumulator births/deaths (the true expected
rate is well under 1 person/day, so a naive `round()` would floor
growth to zero forever — same pattern as terrain evolution's roll-
batches) scaled by an `avg_hunger` that exponentially smooths toward
the settlement's individually-simulated average (a district has no
farms/foraging of its own — a documented simplification, flagged in
`DISTRICT_HUNGER_SMOOTHING`'s docstring), plus a small per-capita
passive `Settlement.materials` contribution — a collectivized resident
is still real background economic activity, not narrative fluff.
Sustained high hunger genuinely can dissolve a district to nothing,
the same real consequence starvation already has for individuals.

New `SimulationEngine._tick_districts` (day_end cadence, alongside
`_deliver_letters`): calls the collectivization check, then ticks
every district; narrates a first-district-founding and a dissolution
via `_log`/`_append_highlight`, mirrors into `village_pillar.remember`
(Tier 0's established pattern) and `_append_emergence` (`"opportunity"`
for founding, `"unexplained_shift"` for dissolution — a real bug
caught and fixed during engine-level verification: the first draft
used `"observation"`, not a member of `emergence.OBSERVATION_KINDS`,
which raised `ValueError` the first time collectivization actually
fired through the real engine). Deliberate scope trim, recorded in
`_tick_districts`'s own docstring rather than left implicit:
`carrying_capacity()` is NOT adjusted for collectivized population this
pass — districts are tracked as a separate, additive population figure
so existing individually-simulated population balance/tuning isn't
disturbed without the ability to live-test the impact; folding
districts into carrying capacity is flagged future work.

`Settlement` (`settlement/buildings.py`) gained `districts`/`next_
district_id` as `SettlementCulture`-backed facade fields (same pattern
as `institutions`), a `"districts"` block in `summary()`, and full
`to_dict`/`from_dict` round-trip support.

UI: new "Districts" main-UI stat tile (collectivized population + ward
names), same placement discipline as "Institutions"/"Social hub."

Verified: `ast.parse()` clean across all four touched/new files; direct
production-path smoke tests against the real `Population`/`Settlement`
classes (collectivization crossing the cap into two districts,
per-survivor Ledger cleanup, materials contribution, starvation-driven
dissolution via the real `tick_district` math, core-cast protection,
below-cap no-op, `to_dict`/`from_dict` round-trip); a real engine-level
test (temporarily lowered `DISTRICT_INDIVIDUAL_CAP`/`DISTRICT_MAX_
POPULATION`, ran 3000 real ticks through `SimulationEngine._tick_once`
with LLM disabled, confirmed districts formed/narrated/round-tripped
through the actual production code path — this is where the
`_append_emergence` kind bug above was caught and fixed);
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
no native module touched by this change.

## [1.34.21] — Tier 0.5 closed; per-agent cognition scoped to Tier 3

Explicit user instruction: "Scope this problem for some other tier
and finish tier0.5 now" — the per-agent-cognition volume-safe design
flagged as the practical ceiling of the Tier 0 mirror pattern (v1.34.7
onward, most recently v1.34.20's own closing note), plus closing out
every remaining item in Tier 0.5 (docs/ROADMAP-2026-07-REMAINING.md,
filed v1.34.4 from a live-diagnostic report — ten items, D1-D10).

**Per-agent cognition, scoped not built**: filed as Tier 3 item 30 —
mirroring per-agent cognition wholesale would flood a pillar's bounded
memory FIFO within days of sim time (once per core-cast member per
day, unlike every settlement-level mirror's flat round-robin volume).
Three volume-gate candidates named for a future pass to choose between
(goal-change-only mirroring matching dialogue's own `surfaced`/`is_llm`
shape; a per-agent significance threshold reusing `_is_significant_
moment`; one settlement-level daily digest instead of one write per
agent) — not designed further, a real decision for later.

**Tier 0.5, item by item** (this environment has no live LLM server,
so D1-D4/D9's live-measurement asks are re-confirmed via code-level
re-audit against the same diagnosed mechanisms, not re-run against
real Ollama traffic):

- **D5 (shipped)**: `rule_propose`'s malformed-JSON reports re-
  diagnosed. The original "give it a JSON schema" framing would have
  silently killed its reasoning trace (`deep_reasoning=True` since
  v1.3.37; `_schedule_llm_job`'s own rule makes reasoning and a schema
  mutually exclusive) — exactly the tradeoff `beliefs`/`personal_
  belief` deliberately avoided by having their schemas removed in that
  same pass. Applied the `PERSONAL_BELIEF_NUM_PREDICT_MULT` fix shape
  instead: new `RULE_PROPOSE_NUM_PREDICT_MULT=2.0` gives `rule_
  propose`'s 10-field contract (close to `personal_belief`'s own
  diagnosed shape) real token headroom without touching the schema
  question. Verified via a direct production-path smoke test
  confirming the real call site passes the multiplier through.
- **D1/D2 (re-confirmed, no change)**: the B2 cold-start math and
  every `_detect_reflection_pattern` threshold still read as
  reasonable on inspection; lowering any of them without a live
  long-run measurement would be the "premature conclusion" the item's
  own framing warns against. Existing `Pillar.turns_processed`
  visibility (v1.23.1) already makes the cold start legible.
- **D3 (audited, no gap)**: the large majority of `_maybe_schedule_*`
  jobs already gate on a real state change; the handful that don't
  (chronicle/documentary/musing/town_brain's narration) are
  deliberately ambient texture by design, the same class v1.34.20's
  own skip list already declined to treat as a bug.
- **D4 (audited, no demotion)**: the recorder tooling D4 asks to read
  from already exists; no live archive exists here to read a real
  measured delta from, and the item's own hard stop rules out
  demoting any reasoning task on code inspection alone.
- **D6 (scoped, not built)**: `Ledger` is genuinely O(population)
  per agent with no locality partition, confirmed via code read.
  Real design, paired with Tier 5's B10 (spatial locality
  partitioning) per the original entry's own note.
- **D7 (closed, no action)**: was always "do more of what's already
  working" — Tier 0's pillar-wiring work through v1.34.20 already is
  that.
- **D8 (scoped, not built)**: a belief life-cycle terminal status is
  real and buildable, but overlaps B8's own un-shipped `reinforce`/
  `reinterpret` closely enough that they should be one design effort,
  not two — left for a future pass naming either item.
- **D9 (substantially already closed)**: `_last_llm_calls[name]`
  already carries `structured_input` and is already exposed via
  `full_diagnostics()` — "why did this happen" is already one dev-
  console click away for a job's latest firing. The real residual
  (linking it to a SPECIFIC formed entity, not just the task's latest
  call) needs new per-entity provenance tagging, real future work.
- **D10 (attempted, honestly incomplete)**: tried for a soak past the
  prior ~20,000-tick longest (60k, then 30k ticks); per-tick cost
  grows with population, and this session's time budget ran out
  before either finished (killed ~10,000 ticks in, no failure
  observed up to that point — not reported as a completed
  re-verification). What's actually confirmed this pass: the standing
  4,000-tick soak + round-trip shows no regression from D5's change.
  A genuine 60k+-tick structural re-check is a straightforward rerun
  needing more wall-clock budget than this pass had, not a design
  question — still open. The content half (digest-of-digest
  coherence) needs a real LLM regardless, unchanged from before.

Verified: `ast.parse()` clean; a direct production-path smoke test for
D5's fix; `scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-
identical; the standing 4,000-tick LLM-disabled soak plus a full
`to_dict()`/`from_dict()` round-trip.

## [1.34.20] — Fifth slice: closes out attention-scaled inbox/outbox coverage

Explicit user instruction: "Continue and finish attention scaled site
in one go." Fourteen more real B4 arrows in a single batch, one per
remaining job judged to carry genuine cross-pillar content — closes
the decision for every one of the 34 attention-scaled sites (v1.34.18)
rather than leaving the rest ambiguously open.

New arrows: Village->Humans (`tradition`, `folklore`, `festival`,
`institution_belief`, `diplomacy`), Village->Reflection
(`legend_detection`, `laws`), Village->Innovation (`guild_founding`),
Humans->Reflection (`personal_belief`), Humans->Village (`fission`,
`migration_decision`), Innovation->Village (`ontology_evolution`'s
merge and evolve branches, `composite_entity`).

Deliberately, explicitly NOT given an arrow: `chronicle`/
`documentary`/`musing` (pure narration, no new cross-pillar fact);
`culture_digest`/`institution_culture` (reflexive self-model digests,
already mirrored); `caravan` (no single clear pillar recipient);
`dream` (its own docstring invokes the same Phase G ambiguity
discipline that kept `omen`/`consciousness` out of B4 messaging);
`memory_drift`/`record`/`mind`-retry/`noncore_nudge`/`letter`
(per-agent jobs judged narrower than `personal_belief`, kept out to
avoid setting an arrow-per-per-agent-job precedent). Total B4 arrows
now 24.

Verified: `ast.parse()` clean; an indent-consistency scan across
every `_send_pillar_message` site (0 real mismatches — the one
flagged case is the same pre-existing, correctly-nested `beliefs`
confidence-gated site); a variable-scope sanity scan (one flagged
false positive confirmed fine by direct read); `scripts/verify_
native_soak.py` (2 seeds x 800 ticks) byte-identical; a 4000-tick
LLM-disabled engine soak plus round-trip, clean; direct production-
path smoke tests for `tradition`, `personal_belief`, and `ontology_
evolution`'s merge branch — all three confirmed populating the
correct outbox/inbox pair.

This closes out attention-budget arbitration and inbox/outbox
coverage decisions for the Tier 0 mirror sites named in v1.34.16's
original scoping. Remaining genuinely open: per-agent cognition's own
volume-safe design — the practical ceiling of this pattern.

## [1.34.19] — Fourth slice: three more B4 inbox/outbox arrows

Explicit user instruction: "Continue with next milestone" — following
directly off v1.34.18's own "Next Milestone" note (extend inbox/
outbox participation further, 31 of the 34 attention-scaled sites had
no arrow yet).

Three more real B4 arrows, chosen for genuine content value rather
than mechanical coverage of all 31 remaining sites:

- **Village->Reflection** (`observation`) on `rule_propose`: a rule
  that survived the counterfactual sandbox and went live is exactly
  the kind of real self-modification event Reflection's meta-
  cognition should observe directly, not just notice secondhand via
  the shared Emergence stream.
- **A third Village->Humans** (`observation`) arrow on `religion`: a
  crystallized faith is a real belief-shaping fact about specific
  living people.
- **A second Reflection->Village** (`observation`) arrow on
  `self_tuning` (the numeric-nudge job, distinct from
  `self_tuning_advisory`'s existing `theory` arrow): a genuinely
  APPLIED, sandbox-validated governor adjustment is a settled fact
  about how Hearthmind changed itself, not a revisable theory.

`omen` deliberately NOT given an arrow — the v1.34.9 explicit user
decision to "ignore Phase G for this one completely" was scoped
narrowly to that one `nature_pillar.world_model` mirror, not a
blanket license to route omens through B4 messaging too. Total B4
arrows now ten.

Verified: `ast.parse()` clean; an indent-consistency scan over every
`_send_pillar_message` site (0 real mismatches — the one flagged case
is the same pre-existing, correctly-nested `beliefs` confidence-gated
site from earlier passes); `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical; a 4000-tick LLM-disabled engine soak plus
round-trip, clean; direct production-path smoke tests for all three
new arrows — `rule_propose` through its real sandboxed closure with a
fake always-safe counterfactual verdict, `religion` with a forced
`forms: true` result (its fallback always means "not yet" by design),
and `self_tuning` with a seeded `supported` hypothesis naming a real
tunable governor — all three confirmed populating the correct
outbox/inbox pair with the correct `kind`.

Still open: 28 of the 34 attention-scaled sites have no matching
inbox/outbox arrow; per-agent cognition remains the one deliberately-
unmirrored Tier 0 gap.

## [1.34.18] — Third slice: attention-budget arbitration for 34 sites + three new B4 arrows

Explicit user instruction: "Extend to other sites" — following
directly off v1.34.17's own "still fully open" note (attention-
budget arbitration and inbox/outbox participation for the ~39 Tier 0
sites that gained observe/interpret cycling in that pass).

**Attention-budget arbitration**: every one of the 34 settlement
jobs that previously called the flat `_settlement_job_backpressured()`
gate now calls `_pillar_interpret_backpressured(pillar)` instead —
the same priority-scaled tolerance function `town_brain` got in
v1.34.16, mapped to each job's owning pillar: village (chronicle,
documentary, tradition, folklore, legend_detection, rule_proposal,
festival, religion, culture_digest, institution_culture, caravan,
faction, guild_founding, institution_belief, diplomacy, laws),
humans (personal_belief, dream, memory_drift, record x2, mind-retry,
noncore_nudge, letter, fission, migration_decision), innovation
(invention, ontology_evolution, composite_entity), nature
(species_variant, omen), reflection (consciousness, self_tuning,
musing). `_maybe_interpret_rumor` deliberately untouched — it already
has its own bespoke backpressure fraction, an earlier design decision
unrelated to this gap. Applied as a pure expression swap (each site's
`if self._settlement_job_backpressured():` became `if self.
_pillar_interpret_backpressured("<pillar>"):`, same line, same
indentation) rather than an insertion, so none of the indentation/
scope risk v1.34.17's `_append_emergence` insertions carried applies
here — verified via a line-by-line diff confirming only the call
argument changed at each of the 34 sites.

**Inbox/outbox participation**: three new B4 arrows, chosen for
genuinely useful cross-pillar content rather than mechanically
covering all 34 newly-scaled sites — Innovation->Reflection
(`discovery`) on `invention`, Nature->Innovation (`observation`) on
`species_variant`, and a second Village->Humans (`observation`)
arrow on `faction`. Brings the total B4 arrows to seven: the
original three (Nature->Village, Village->Innovation, Innovation-
>Village), v1.34.16's Reflection->Village, and these three.

Verified: `ast.parse()` clean; an indent-consistency scan over every
`_send_pillar_message` call site (0 mismatches — the three new sites
match their enclosing `apply()` body's indent); `scripts/verify_
native_soak.py` (2 seeds x 800 ticks) byte-identical; a 4000-tick
LLM-disabled engine soak plus round-trip, clean; direct production-
path smoke tests confirming `invention` and `species_variant` both
fire through their real (unpatched) `_pillar_interpret_backpressured`
gate and correctly populate the new arrows' outbox/inbox pairs.

Still open: 31 of the 34 attention-scaled sites don't yet have a
matching inbox/outbox arrow; per-agent cognition remains the one
deliberately-unmirrored Tier 0 gap.

## [1.34.17] — Second slice: extend observe/interpret cycling to the remaining ~39 Tier 0 mirror sites

Explicit user instruction: "Extend to 45 tier 0 sites" — directly
following v1.34.16's own "deliberately NOT attempted this pass"
note, which named this exact follow-up.

Applied the same `_append_emergence` call v1.34.16 added to 6
representative Tier 0 mirror sites to the remaining ~39: village
(naming, town_brain, chronicle, documentary, chronicler, away_digest,
tradition, folklore, legend_detection, rule_propose, festival,
religion, institution_culture, caravan, beliefs, faction,
institution_belief, diplomacy, laws), humans (narrative_direction,
personal_belief, dream, memory_drift, skill_mastery, record, mind,
noncore_nudge, letter, migration_decision, rumor_interpret,
voice-pair dialogue), innovation (invention, ontology_proposal,
ontology_evolution's combine/evolve branches, era_branch), nature
(nature_mind, omen), reflection (musing, self_tuning, reflection_
question). Every one of these now competes for its pillar's bounded
`working_memory` on the next `observe` turn (B2), same as the six
v1.34.16 sites — closing the gap that made a Tier 0 mirror's content,
however significant, structurally invisible to its own pillar's
observe/interpret cycle.

Applied via a scripted pass (39 sites in one batch, not 39 individual
edits) rather than 39 hand-written insertions — this surfaced two
real bugs the script's own "success" output did not catch, both
found and fixed via independent post-hoc verification, not trusted
from the script:

1. **Silent non-write**: the script's first run computed all 39
   replacements correctly in memory but only wrote the file inside
   an `if not missing: ...` branch — one of 40 candidate anchors
   (`institution_belief`'s `remember()` call) was ambiguous, so the
   whole file was never written despite the script printing "applied:
   39 of 40." Fixed by rewriting the script to always write the file
   and report failures separately.

2. **Indentation/scope bugs** (two, both real, both would have
   shipped silently without dedicated verification):
   - `beliefs`' new-belief branch sits inside an `else:` block at
     16-space indent; the inserted `_append_emergence` landed at 12
     spaces, which parsed as valid Python but de-scoped the following
     B4 `if entry["confidence"] >= 0.5: self._send_pillar_message(...)`
     block out of the `else:` it belonged in. Caught via `ast.parse()`
     raising `IndentationError`; fixed by re-indenting to 16 spaces.
   - `rule_propose`'s apply() nests its rule-registration logic
     inside an `async def _sandbox_and_register():` closure (gated on
     the counterfactual-sandbox verdict). The inserted call landed
     OUTSIDE that closure, at `apply()`'s own indent — syntactically
     valid, but referencing `rule` (a name that only exists inside
     the closure) and firing unconditionally regardless of the
     sandbox verdict; this would have raised `NameError` on every
     real firing. Caught via a scripted indent-consistency scan
     (compare each inserted call's indent against its preceding
     `remember()`/`upsert_world_model()` line); fixed by moving the
     call inside the closure, correctly gated on `verdict["safe"]`.

Verified: an automated indent-consistency scan across every
`_append_emergence` call site in `engine.py` (0 real mismatches after
the two fixes — the one remaining flagged case is a pre-existing,
correctly-nested site in `_detect_social_hub`, unrelated to this
pass); `ast.parse()` clean; direct production-path smoke tests for
`naming`/`town_brain` (both confirmed writing a real emergence entry)
and, specifically targeting the two fixed bugs, `rule_propose`
(confirmed firing end-to-end through the real `_sandbox_and_register`
closure with a fake always-safe counterfactual verdict) and `beliefs`
(confirmed the new-belief branch fires correctly on a pillar's real
`interpret` turn, after an `observe` turn correctly consumes the
first call per B2's existing cycling); `scripts/verify_native_soak.
py` (2 seeds x 800 ticks) byte-identical — no native module touched;
a 4000-tick LLM-disabled engine soak plus a full `to_dict()`/
`from_dict()` round-trip, both clean.

Still fully open, unchanged from v1.34.16: attention-budget
arbitration and inbox/outbox participation for these ~39 sites (this
slice only extended observe/interpret cycling, matching the literal
"extend to 45 tier 0 sites" ask) — `town_brain` remains the only
site with real attention-budget arbitration, Reflection->Village
remains the only new inbox/outbox arrow, and per-agent cognition
stays the one deliberately-unmirrored gap.

## [1.34.16] — First slice: observe/interpret cycling, attention-budget arbitration, and inbox/outbox for Tier 0 mirrors

Explicit user instruction: "Start observe/interpret cycling,
attention-budget arbitration, and inbox/outbox participation" —
continuing directly off Tier 0's closing note (these three items were
flagged as the next tier once mirroring hit its practical ceiling).

Root gap found first: every Tier 0 mirror (the ~50 jobs wired across
the last several passes) writes DIRECTLY into `pillar.world_model`/
`memory`, bypassing `_pillar_observe_turn` entirely — that helper
only ever reads `World.emergence_log_recent()` (A22), and none of the
Tier 0 mirror sites populate it (only the original 8 `_append_
highlight` kinds do). So however significant a Tier 0 mirror's
content was, it was structurally invisible to its own pillar's
observe/interpret cycle and to inter-pillar messaging — a direct
write, never competing for bounded attention, never reachable by
another pillar.

Scoped a first slice touching all three named mechanisms on 5-6
concrete sites, same "one real representative site, not a blind pass
across all ~50" discipline every earlier B2/B3/B4 pass used:

**Observe/interpret cycling**: `guild_founding` (Village), `fission`
(Humans+Village), `composite_entity` (Innovation), `species_variant`
(Nature), `self_tuning_advisory` (Reflection+Village) now also call
`_append_emergence`, pillar-tagged — each genuinely competes for its
pillar's bounded `working_memory` on the next `observe` turn,
salience-ranked against everything else, not guaranteed visibility.

**Attention-budget arbitration**: `_maybe_schedule_town_brain`
(Village's single most significant civic decision) now uses
`_pillar_interpret_backpressured("village")` — the same priority-
scaled tolerance B3 built for the pillar's own `interpret` turn —
instead of the flat `_settlement_job_backpressured()` gate. Reused
directly (the function only reads/checks state, never mutates
`cycle_stage`), not reimplemented.

**Inbox/outbox participation**: a new Reflection -> Village arrow
(`kind="theory"`) fires whenever `self_tuning_advisory` forms.
Verified end-to-end, not just "message sent": a real `_pillar_
observe_turn("village")` call delivers the queued message into
`working_memory` and clears it from `inbox`, closing the full B4 loop
with genuinely new content for the first time since the original
three arrows (Nature->Village, Village->Innovation,
Innovation->Village).

Deliberately not attempted: extending this same pattern to the other
~45 Tier 0 mirror sites (mechanical repetition, not a new design
question — future direction can ask for "more of these" directly);
reverse-direction disagreement classification for the new arrow (a
pre-existing flagged gap on the original Nature->Village site too).

Verified: all six changes confirmed via direct production-path smoke
tests, including one exercising the full B4 round-trip (send -> inbox
-> `_pillar_observe_turn` -> working_memory, inbox cleared). A
4000-tick LLM-disabled engine soak confirms no regression; `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical — no
native module touched.

## [1.34.15] — Tier 0 final audit slice: voice-pair dialogue mirrored; cognition scoped as the one remaining gap

Explicit user instruction: "Continue tier 0." A final audit pass over
every `_schedule_llm_job`/structurally-distinct call site found one
real remaining candidate and corrected one stale note from the prior
pass's own changelog.

`_apply_pending_dialogue_results`'s `is_llm` branch now mirrors into
Humans' memory. Genuinely volume-safe, unlike dialogue in general:
`is_llm` can ONLY ever be the one dedicated voice pair (`Population.
voice_pair_ids`, since v1.4.0's redesign collapsed all LLM dialogue to
a single ongoing conversation thread) — every other pair resolves
deterministically and structurally never reaches this branch, so this
reads Humans' actual protagonists' conversation without any new
volume gate needed. Humans=11 -> 12.

Correction: v1.34.14's changelog described `self_tuning`'s numeric-
nudge path as still unmirrored ("self_tuning's numeric-nudge sibling
call"). Re-checked while auditing this slice: it was already mirrored
— Tier 0's very first slice (`_maybe_schedule_self_tuning`'s `applied`
outcome already writes to `reflection_pillar`). No code change; the
prior changelog entry was simply wrong on this one point.

Coverage now: Innovation=5, Village=22, Humans=12, Nature=3,
Reflection=6.

Audited but NOT mirrored: per-agent cognition (`_run_cognition`/
`_apply_pending_cognition_results`) is the one real remaining gap —
genuine per-agent judgment, once a day, for every core-cast agent,
that Humans' pillar currently has zero visibility into. Deliberately
not attempted: mirroring it wholesale would flood the small bounded
`memory` FIFO with routine goal-of-the-day noise within days of sim
time and evict everything else — dialogue's `is_llm`/`surfaced` flags
gave that same problem a volume gate for free, cognition has no
equivalent signal today. Needs its own scoped design (e.g., mirror
only a goal change carrying a genuinely novel LLM-authored `reason`)
before attempting, same standing "build only on future explicit
direction" rule as the scoped-not-built Nature causal-reasoning job.

This is the practical ceiling of "mirror an existing job's output" —
everything else left is either the cognition-volume design problem
above, or a different tier of work entirely (observe/interpret
cycling, attention-budget arbitration, inbox/outbox participation).

Verified: the new mirror confirmed via a direct production-path smoke
test (a synthetic `_pending_dialogue_results` entry with `is_llm=True`
driven through the real `_apply_pending_dialogue_results` code path).
A 4000-tick LLM-disabled engine soak confirms no regression; `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical — no
native module touched.

## [1.34.14] — Tier 0 batch 3: closes out nearly every remaining job; consciousness mirrored (explicit user decision)

Explicit user instruction: "Continue tier 0 with many steps at once
and ask about consciousness" — third multi-job batch, plus a direct
`AskUserQuestion` about the one flagged-but-unresolved pillar-mirror
gap: `consciousness` (Phase G/N's ambiguity discipline).

Six real jobs mirrored: `away_digest`/`chronicler` -> Village
(memory-only — an on-demand recap/Q&A exchange). `mind`/`rumor_
interpret` -> Humans (memory-only; `mind`'s mirror is gated to a
genuine non-fallback answer only, since the fallback path just
restates the agent's existing identity text, not new content).
`self_tuning_advisory` -> Reflection (`world_model` hypothesis +
memory — Reflection's own free-standing advice on something it has
no tunable governor for, genuinely uncertain by design pending a
human's accept/reject review).

`consciousness`: asked directly via `AskUserQuestion` with three
options — mirror with real content (hypothesis-only, same shape
`omen` got), mirror occurrence-only with no content, or leave
permanently unmirrored. Explicit user answer: "Mirror into
Reflection, hypothesis-only." Implemented at the `if kind != "none"`
branch inside `_maybe_schedule_consciousness`'s `apply()`, writing
the actual `kind`/`detail` — justified because Reflection's `world_
model`/`memory` sit at the same dev-console-only depth the existing
`consciousness_intervention_log` already has (never main-UI); the one
line that DOES reach players (`_log("consciousness_intervention", ...)`)
is untouched and stays exactly as vague as before ("Something in
{settlement} quietly shifted") — nothing player-visible changed.

`sim_summary` considered and deliberately skipped — it's an on-demand
restatement of population/settlement/mood stats already covered by
`town_brain` and other real mirrors, not distinct judgment or texture.

Coverage now: Innovation=5, Village=22, Humans=11, Nature=3,
Reflection=6. This closes out nearly every `_schedule_llm_job` call
site reachable by the mirroring pattern — what's left (dialogue's own
`_run_dialogue` path, per-agent cognition's `_run_cognition` path,
`self_tuning`'s numeric-nudge sibling, `pillar_chat` which already
reaches its pillar directly, `geography` which has no LLM call) isn't
further mirror work, it's the next tier: observe/interpret cycling,
attention-budget arbitration, inbox/outbox participation.

Verified: all six new mirrors confirmed via direct production-path
smoke tests (a real `FakeClient` driving each job through its actual
gating conditions, including `_author_one_mind` and `_maybe_interpret_
rumor` called directly with synthetic agents). A 4000-tick LLM-
disabled engine soak confirms no regression in the normal tick path;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
— no native module touched.

## [1.34.13] — Tier 0 batch 2: nine more Village jobs, three more Humans jobs

Explicit user instruction: "Continue tier 0 with many steps at once"
— second multi-job batch, twelve real jobs mirrored in one pass.

Village pillar (11 -> 20 real wired jobs): `naming` (`world_model`
observation — a settlement's own name is a real settled fact),
`tradition`/`folklore`/`legend_detection` (memory-only — an
occurrence, tale, or legend, not a single revisable theory the way a
law/religion is), `culture_digest` (`world_model` observation — the
settlement's own condensed self-understanding), `institution_culture`
(memory-only — one institution's own independently-authored
character), `caravan` (memory-only — an occurrence), `town_brain`
(`world_model` observation — THE central Village decision; mirrored
the instant `town_brain.compute_priority` resolves deterministically,
before the narration-only LLM call even schedules, since the decision
itself doesn't need to wait on inference), `diplomacy` (memory-only —
spans two settlements, so it lands in the one shared world-scoped
Village pillar).

Humans pillar (7 -> 9): `personal_belief` (memory-only — one
individual's own private theory about their life), `record`
(memory-only — mirrored once at the single `_apply_record` call both
the LLM and fallback narration paths already share, so a dying
villager's last words reach the pillar either way), `fission`
(memory-only — a leader's own major life decision to found a new
settlement, same treatment `migration_decision` already gets).

Coverage now: Innovation=5, Village=20, Humans=9, Nature=3,
Reflection=4.

Verified: all twelve new mirrors confirmed via one combined direct
production-path smoke test — a real `FakeClient` driving each job
through its actual gating conditions, including season/year-cadence
jobs called directly with a forced boundary event (same pattern
`religion` used in an earlier slice) and monthly-cadence jobs driven
through a real day-of-month retry loop. A 4000-tick LLM-disabled
engine soak confirms no regression in the normal tick path; `scripts/
verify_native_soak.py` (2 seeds x 800 ticks) byte-identical — no
native module touched.

## [1.34.12] — Tier 0 batch: six more Village jobs, two more Humans jobs

Explicit user instruction: "Continue tier 0 but do many steps at
once" — the first multi-job batch in this series instead of the usual
one-or-two-job pass. Re-read each remaining `_maybe_schedule_*` call
site's actual apply() logic (not just its name) to find genuine fits
for the two pillars behind their domain's natural job count (Village
was still at 5 despite having by far the largest number of culture/
civic LLM jobs in the codebase; Humans had room too).

Village pillar (5 -> 11 real wired jobs): `chronicle` and
`documentary` (both memory-only — a monthly/yearly narrative is
Village's own retelling, not a single standing fact the way a law or
religion is), `festival` (memory-only — an occurrence), `religion`
(`world_model` observation + memory — a crystallized faith is a real,
high-confidence settled fact, same treatment `laws`/`rule_propose`
already get), `faction` (`world_model` observation + memory — a
detected, named faction is a real settled social fact), `guild_
founding` (`world_model` observation + memory — a deliberately
founded guild is a real settled institutional fact).

Humans pillar (5 -> 7 real wired jobs): `letter` (memory-only — one
individual's own written words to someone far away), `noncore_nudge`
(memory-only — an ordinary villager's own quiet moment of change,
gated inside the job's own `shifts=True` branch so a no-op nudge
correctly writes nothing).

Coverage now: Innovation=5, Village=11, Humans=7, Nature=3,
Reflection=4.

Verified: all eight new mirrors confirmed via one combined direct
production-path smoke test — a real `FakeClient` driving each job
through its actual gating conditions (including working around two
real test-setup gaps that were NOT product bugs: a test harness that
manually advances `World.clock.tick_count` without calling
`_tick_once()` never clears `SimulationEngine._reserved_this_tick`,
the same v1.3.2-documented same-tick reservation counter — real
production ticking clears it every tick, only a hand-rolled test loop
skipping `_tick_once()` needs a manual reset; and `guild_founding`'s
own re-validation at apply time genuinely requires two agents at
`GUILD_SKILL_MASTERY_THRESHOLD` in the named skill, not just a
synthetic candidate tuple). A 4000-tick LLM-disabled engine soak
confirms no regression in the normal tick path; `scripts/verify_
native_soak.py` (2 seeds x 800 ticks) byte-identical — no native
module touched.

## [1.34.11] — Tier 0 ninth/tenth slice: Innovation's fifth job (era_branch), Reflection's fourth job (musing)

Explicit user instruction: "Continue tier 0."

`_maybe_schedule_era_branch` (Innovation's fifth wired job) now
mirrors the settlement's era-branch lean into `innovation_pillar.
world_model` (`status="observation"`, `source="era_branch"`) plus a
memory note — the branch itself (industrious/scholarly/devout/
mercantile/agrarian) is computed deterministically before the one LLM
call fires, and that call is narration-only, so this is a real
settled fact, same treatment `composite_entity` already gets.
`_maybe_schedule_musing` (Reflection's fourth wired job) now writes a
memory-only note into `reflection_pillar.memory` when a musing forms
— no `world_model` entry, since the underlying theory (if any) is
already tracked in `reflection_notebook`; a musing is Reflection's own
passing voice, same "individual moment, not a collective theory"
reasoning `dream`/`skill_mastery` already established for their
pillars.

Nature re-checked for a fourth candidate; none found this pass either
— every remaining unmirrored `_maybe_schedule_*` job belongs to
another pillar's domain (dialogue/culture/politics/founding all
Village- or Humans-flavored, caravan/diplomacy external-facing).

Coverage now: Innovation=5, Village=5, Humans=5, Nature=3,
Reflection=4.

Verified: both new mirrors confirmed via direct production-path smoke
tests (a real `FakeClient` driving each job through its actual gating
conditions — `era_branch` called directly with a synthetic settlement/
era, `musing` gated on a synthetic open `reflection_notebook`
hypothesis entry); a 4000-tick LLM-disabled engine soak confirms no
regression in the normal tick path; `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical — no native module touched.

## [1.34.10] — Tier 0 seventh/eighth slice: Village's fifth job (laws), Humans' fifth job (skill_mastery); Nature cognition gap scoped

Explicit user instruction: "Nature can have some many things though
like ecology, forests, wildlife, geography are they there?" followed
by "Scope that out and continue tier 0" — a genuine question about
Nature's domain coverage, then a dual instruction to (a) write a
scoping/design doc for a new, genuinely reactive Nature cognition job
and (b) keep widening pillar mirror coverage on other pillars.

**Continue tier 0**: `_maybe_schedule_laws` (Village's fifth wired
job) now mirrors a newly-formed law/custom/taboo into `village_
pillar.world_model` (`status="observation"`, `source="laws"`) plus a
memory note — same treatment `rule_propose` already gets, a codified
norm is a real settled civic fact. `_maybe_schedule_skill_mastery`
(Humans' fifth wired job) now writes a memory-only note into `humans_
pillar.memory` when a core-cast agent's LLM-narrated mastery
reflection lands — no `world_model` entry, matching `dream`'s existing
"individual, not collective theory" reasoning. Caught and fixed a real
closure late-binding risk while editing `_maybe_schedule_skill_
mastery`'s existing `apply()` — its `skill` loop variable wasn't
captured as a default argument like its four siblings already were,
which would have read the wrong skill name if multiple masteries
resolved out of order in the same tick.

Coverage now: Innovation=4, Village=5, Humans=5, Nature=3,
Reflection=3.

**Nature domain question, answered**: `world/geography.py`'s naming
is fully procedural (zero LLM, v1.3.35); `llm/nature_mind.py` already
reasons over real wildlife/climate/scar/fallow Body state — so
forests/wildlife/climate genuinely DO reach Nature's Mind already, just
through one general seasonal belief-revision pass, never a reaction to
one specific ecological event/anomaly. Scoped (not built) a new
`_maybe_schedule_nature_causal_reasoning`-shaped job in docs/ROADMAP-
2026-07-REMAINING.md's Tier 0 section: reactive (not cadence-gated,
same shape `skill_mastery` already established), grounded in ONE
specific detected Body-state anomaly (candidates: a wildlife
herd/pack nearing local extinction, a regional disaster-scar spike, a
forest-succession stall past its expected window), output written both
to `nature_pillar.world_model` (`status="hypothesis"`, never
`"observation"`) and to `world.ontology.CausalThread` (reusing the
mechanism v1.3.41 built for dispute outcomes, surfaced via the
existing "🔗 causal threads" panel — no new UI). `critical=True` per
Constitution §3/§7. Full scoping rationale in the roadmap doc; build
only on future explicit direction naming this item.

Verified: both new mirrors confirmed via direct production-path smoke
tests (a real `FakeClient` driving each job through its actual gating
conditions end to end, including discovering and working around two
test-setup gaps that were NOT product bugs — `parse_laws` legitimately
returns `None` for an empty response per its own "not yet" design, and
a fresh test settlement has no name until enough ticks pass for the
existing placeholder-naming mechanism to fire); a 4000-tick LLM-
disabled engine soak confirms no regression in the normal tick path;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
no native module touched.

## [1.34.9] — Tier 0 sixth slice: Nature's third job (omen), explicit Phase G exception

Explicit user instruction: "continue tier 0," followed by a direct
question about the flagged Nature/omen conflict (`omen` is the best-
fitting remaining content match for Nature, but sits under Phase G's
"never confirm anything supernatural" discipline, which a pillar
`world_model` entry's status field would violate). Presented three
options via `AskUserQuestion`; explicit user answer: "You can ignore
phase G for this one completely."

`_maybe_schedule_omen`'s apply() now mirrors into `nature_pillar.
world_model` as a `status="hypothesis"` entry (never `"observation"`
— an omen still isn't a confirmed fact even under this relaxed
treatment) plus a `remember()` note. Nature now at 3 jobs (nature_
mind, species_variant, omen). Scoped narrowly per the user's answer:
only this ONE mirror site treats the omen as a real sensed
impression — every other omen consumer (the settlement stat tile, dev
console, existing narration) is untouched and stays exactly as
ambiguous as before. Phase G's discipline otherwise stands unchanged
everywhere else in the codebase.

Verified: a direct production-path smoke test (temperament pushed
high to raise omen chance, driven through real gating conditions
across many ticks until it fired, confirming the `world_model` entry
and its `hypothesis` status) plus a separate clean 4000-tick
unattended soak, zero exceptions.

## [1.34.8] — Tier 0 fifth slice: Innovation's fourth real job (composite_entity)

Explicit user instruction: "continue tier 0." `_maybe_schedule_
composite_entity` (a real standing building named + given an origin
story, backed by a genuinely new registered `InventedConcept`) now
mirrors into `innovation_pillar.world_model` as an `observation` (a
named place is a settled fact, same treatment `invention`/`ontology_
evolution` already get) plus a `remember()` note. Innovation now at
4 jobs (ontology_proposal, invention, ontology_evolution, composite_
entity).

Verified: a direct production-path smoke test (a real standing HUT
staked out, the job driven through its real gating conditions,
confirming the `world_model` write and the underlying `CompositeEntity`
registration) plus a clean 3000-tick unattended soak, zero exceptions.

## [1.34.7] — Tier 0 fourth slice: Humans' fourth real job (memory_drift)

Explicit user instruction: "continue with tier 0." Extends v1.34.6's
pillar-coverage widening: `_maybe_schedule_memory_drift` (a core-cast
agent's older memory occasionally reinterpreted, "learns like a
human," v0.87.0) now mirrors into `humans_pillar.memory` — memory-
only, same reasoning as `dream`/`migration_decision`: a specific
individual's own reinterpreted memory is not a collective theory.
Humans is now at 4 jobs (narrative_direction, dream, migration_
decision, memory_drift).

Looked for a genuine third Nature job again this pass and found none
worth forcing: `omen` is the closest remaining candidate by content
(land/weather-adjacent flavor) but sits explicitly under Phase G's
ambiguity discipline — its own module docstring says it must never
confirm anything, and a pillar `world_model` entry's `status` field
(`observation`/`hypothesis`) would do exactly that. Left unmirrored
rather than forced.

Verified: a direct production-path smoke test (a real core-cast agent
given two memories via the actual `_remember` helper, the job driven
through its real monthly-gate/day-of-month/chance-roll conditions
until it fired, confirming the correct `humans_pillar.memory` write)
plus a clean 4000-tick unattended soak (fake LLM client, LLM
"enabled"), zero exceptions.

## [1.34.6] — Tier 0 third slice: Reflection/Village get one more real job each; a real bug fixed along the way

Explicit user instruction: "continue with tier 0." Extends v1.32.0/
v1.33.0's pillar-coverage widening to the two pillars still trailing:

- **Reflection** (now 3 jobs): `_maybe_schedule_reflection_question`
  (its own distinct job name/prompt/apply, called from within
  `_maybe_schedule_reflection`'s flow but a genuinely separate
  production call site) now mirrors into `reflection_pillar.memory` —
  memory-only, since an open question is explicitly not a settled
  belief (the notebook entry itself carries `status="open"`,
  `confidence=None`).
- **Village** (now 4 jobs): `_maybe_schedule_rule_proposal` mirrors a
  rule that survived the counterfactual sandbox and went live into
  `village_pillar.world_model` as an `observation` (a real settled
  civic fact, not a theory) plus a `remember()` note.

**Real bug found and fixed while verifying the above**, unrelated to
this session's own change but surfaced by it: `_musing_subject()`
selected the newest `reflection_notebook` entry with `status="open"`
without filtering by `kind`. A `"question"` entry (real, pre-existing
shape — `confidence=None` by design) could slip through and reach
`llm/musing.py`'s `build_prompt`, which formats `{subject['confidence']
:.2f}` assuming a hypothesis — a genuine `TypeError` crash on `None`.
This method's own docstring says "prefer the newest OPEN hypothesis,"
so the fix is a one-line filter narrowing the query to `kind ==
"hypothesis"`, matching stated intent rather than changing behavior.

Verified: direct production-path smoke tests for both new mirror
sites (a synthetic `reflection_question` call confirming the memory
note, a real `rule_propose` call through the counterfactual sandbox
confirming the `world_model` entry and the underlying `TriggerRule`
itself), plus the exact repro that surfaced the musing bug (re-run
post-fix, no crash). A separate unattended 4000-tick soak (fake LLM
client, LLM "enabled") ran clean with zero exceptions.

Pillar coverage is now Innovation=3, Village=4, Humans=3, Nature=2,
Reflection=3 — Nature remains the one pillar without an obvious third
distinct production job; not forced this pass.

## [1.34.5] — The Living Map vision folded into roadmap as Tier 1.5 (docs only)

Explicit user directive: the world map should visually communicate
history — civilization, nature, climate, disasters, and wildlife all
leaving persistent marks — rather than reading as a static procgen
map with agents on top. Twelve numbered points (terrain dynamism,
civilization's visible footprint, nature reclaiming the world, real
map representation for hydrology/ecology/climate, overlay redesign
toward reference-game quality, per-overlay gameplay questions, rivers
that visibly evolve, a visual-history layer, landmark-based base-map
readability, universal system-to-visual coverage, and the standing
philosophy itself). Docs-only.

Filed as `docs/VISION-2026-07-24-LIVINGMAP.md` (M1-M12), same
convention as the project's other large vision docs. Cross-referenced
each point against what already ships rather than treated as
greenfield: the four scar-shaped overlays (mining/disaster/ritual/
ruin), the "🗺️ fields" toggle, layout/architecture/dialect grammar,
and forest reclaim already cover real slices of this. Confirmed by
direct code check (not assumed) that a fully-decayed road leaves no
persistent trace (`RoadNetwork`'s wear dict deletes the position
entirely on full decay) — a genuine gap, not a guess.

`docs/ROADMAP-2026-07-REMAINING.md` gained a new **Tier 1.5**,
sequenced after Tier 1's substrate work and before Tier 2 — several
of the vision's biggest items (real erosion/flooding-reshapes-terrain,
quarry scars as actual elevation change, rivers re-carving their
course) are all blocked on A11's own already-recorded mutable-
elevation item, so this tier can't meaningfully start before that one
substrate item lands. The overlay-redesign half (M6/M7) has no such
blocker — pure rendering work over data already flowing to the
client — and could be pulled forward independently if prioritized
that way later.

Also recorded the standing philosophy itself (M12) directly in
CLAUDE.md's Observatory UI direction section, not just the vision doc
— a design directive should live where future work actually gets
checked against it, same treatment the section's existing rules get.

## [1.34.4] — Ten live-diagnostic findings folded into roadmap as Tier 0.5 (docs only)

Explicit user request: fold ten specific live-run observations
(Reflection/Nature pillar cadence, LLM call-volume/reasoning-tier
audits, rule-generation malformed JSON, social-scaling limits,
cumulative-culture strengthening, belief life cycle, cognition-level
"why" diagnostics, long-horizon memory consolidation) into the current
roadmap. Docs-only.

Filed as a new **Tier 0.5** in `docs/ROADMAP-2026-07-REMAINING.md`,
positioned right after Tier 0 and before Tier 1 — these are
correctness/tuning questions about systems Tier 0 already targets
(pillar cadence) plus A9-shaped audit items, cheaper and more urgent
than starting Tier 1's substrate work. Every item carries the user's
own explicit hard-stop constraint: no change may degrade cognition or
sentience quality, full stop.

Grounded each item against real prior code/history rather than
restating the request verbatim: D1/D2 (Reflection/Nature cadence)
cross-referenced against v1.23.1's own prior diagnosis (B2's observe/
interpret halving, "cold-start latency, not a bug" — but this new
report describes a MUCH longer run still showing the same symptom,
so re-investigation is warranted, not an assumed-solved rehash). D5
(rule-generation malformed JSON) confirmed as a real gap by direct
code check: `rule_proposal` has no entry in `llm/json_schemas.py`'s
constrained-decoding set, unlike the eleven tasks FT.0 already
covers. D6/D8/D9 cross-referenced against real overlapping in-flight
work (Tier 3's A16 graph-algorithms and B8's un-shipped reinforce/
reinterpret, Tier 5's B10 spatial locality and B5.4 "explain this
tick") so a future pass doesn't design the same mechanism twice under
two different names.

## [1.34.3] — HearthBench & Adaptive Runtime checklist folded into roadmap (docs only)

Explicit user request: fold an uploaded checklist
(`HEARTHBENCHANDRUNTIME20260723.md` — Part A HearthBench, a standalone
model-selection benchmark; Part B the Adaptive Runtime, an OS-like
execution layer; Part C where they meet) into the current roadmap,
ordered by how best to implement it after finishing the previous
roadmap items. Docs-only.

Filed the uploaded checklist verbatim as `docs/HEARTHBENCH-RUNTIME-
2026-07-23.md`, same convention as `docs/MASTERCHECKLIST-2026-07-
22.md`. `docs/ROADMAP-2026-07-REMAINING.md` gained a new **Tier 5**
(after the existing Tier 4 standing-discipline items) summarizing
scope and preserving the source doc's own two-track internal SEQUENCE
(Runtime: replay-hash safety net first, then task declaration +
"explain this tick," profiling, timescales/dirty-tracking, budgets/
locality/dormancy, memory/history compression, reference-mode +
escalation ladder, adaptive tuning last; HearthBench: skeleton +
adapter, fixture export, deterministic scorers, CI regression guard,
metrics/diagnostics, reports/score/UI/model-passport, judge scoring,
world-level run last) rather than re-deriving a new ordering — the
source doc's own sequencing already reflects real dependency analysis
(e.g. A5.11's world-level run explicitly can't be meaningful without
B15.5's reference mode existing first).

Sequenced strictly after Tiers 0-4 per the user's own framing
("after finishing the previous items") — explicit rationale recorded:
this is infrastructure for building/measuring Hearthmind, not a
Hearthmind feature itself, and building it before the Body/Mind/Seam
work stabilizes would mean re-benchmarking against a moving target.
Flagged one real overlap worth a fresh look when Tier 5 actually
starts: B9's hierarchical-timescale enforcement covers territory
already partly addressed by the existing B2/B3 attention-scheduler
cadence work (Tier 0), not assumed resolved here.

## [1.34.2] — A9 closed: last real gap fixed, two findings corrected

Explicit user instruction: "expand A9 further, whatever you have
missed. Completely close it." Two parts: fixed the one remaining real
gap, and re-examined two of v1.34.0's own "recorded, not fixed"
findings that turn out to be mischaracterized rather than actual bugs
— closing A9 honestly means correcting an overreach, not forcing an
artificial fix onto working-as-designed code.

**Fixed**: `llm/ontology.py`'s `PRESSURE_SIGNAL_LABELS["materials_
bottleneck"]` has always named a pressure signal that nothing ever
incremented — `Settlement.pattern_signal_counts["materials_
bottleneck"]` could structurally never cross its promotion threshold,
so Innovation's ontology-proposal job could never name THIS specific
pressure even when grounded by it. `_detect_settlement_bottlenecks`
(the existing edge-triggered "materials genuinely ran dry" detector,
v1.4.8) now increments it at the same edge-trigger point it already
emits an Emergence API observation from — same shape as `dispute_
feud`/`nature_adaptation`'s existing increment sites elsewhere in this
file.

**Corrected, not fixed** (re-reading turned up that these were never
real A9 violations):
- `world/architecture_grammar.py`'s per-building descriptor is, by its
  own module docstring, deliberately pure flavor text ("one structural
  descriptor phrase," no mechanical intent) — same category as dream
  text or chronicle narration, which this codebase has never required
  to feed back mechanically. `World.causal_threads` (vision item 3.3,
  "legible causal threads") is the same: an explicitly UI-facing
  feature by its own design doc, not a silently-abandoned producer.
  Flagging either as "write-only" applied A9's producer/consumer bar
  to content that was never meant to clear it.
- `Agent.genome`: re-examined against the audit's own stated verdict
  categories. It has a real producer (conception, with inheritance +
  mutation) AND a real consumer (`Agent.traits`, read everywhere trait
  behavior matters) — a genuine CLOSED LOOP, not "READ-ONLY." The
  earlier finding conflated "never revised post-conception" with "no
  consumer" — but genes not changing from lived experience is
  biologically correct, not a gap; `hardened_traits`' existing
  monthly-reversion-lock mechanism already covers "life events
  permanently reshape behavior" at the phenotype (traits) layer, which
  is the right layer for that, not genotype.

`Settlement.legends`' write-only status stands (unlike the two above,
it's a real, already-separately-tracked gap — A21's own roadmap entry
already names "legend->tradition/institution feedback... remains
open," so it's not a new A9 finding, just not something A9 needs to
additionally claim).

This closes A9 — both a real remaining fix and an honest correction of
scope, not a forced mechanical effect bolted onto intentionally-
decorative content.

Verified: a direct smoke test (`materials=0.0` forces the edge-trigger,
confirms the counter increments) plus a 2000-tick LLM-disabled engine
run, zero exceptions.

## [1.34.1] — A9 second pass: location_character becomes real

Explicit user instruction: "do the second pass" — following up on
v1.34.0's own flagged loudest finding, that `world/spatial_memory.py`'s
`location_character()` (the intended A19 read-side unifier for
mining/disaster/ritual/ruin scars) was itself never called anywhere,
even after that pass gave `mining_scars`/`disaster_scars` a real
consumer via direct duplicate `.get()` calls in `Population._choose_
build_site` instead of routing through the unifier that already
existed for exactly this purpose.

Split `location_character` into `location_character_from_dicts(mining_
scars, disaster_scars, ritual_activity, ruin_scars, x, y)` (the real
logic, every dict optional) + `location_character(world, x, y)` (a
thin wrapper for a future `World`-scoped caller — `_choose_build_site`
is deliberately decoupled from `World`, same as `ruin_scars` already
was, so it can't call the wrapper directly). `_choose_build_site`'s
scoring loop now reads `ruin`/`mining`/`disaster` off ONE `location_
character_from_dicts()` call instead of three separate duplicate
lookups — the unification this module was built for is now the actual
mechanism a real consumer reads from, not a still-unused sibling.
Behavior unchanged (same three score terms, same constants); this is
purely closing the read-side duplication the audit flagged.

Residual, honestly noted rather than overclaimed: the `location_
character(world, x, y)` convenience wrapper itself still has zero
callers — no current caller happens to have `World` in scope where
this fires (`Population`'s build-site logic never does). A future
`World`-scoped consumer (dialogue/cognition location flavor, an NPC
inspector "this ground remembers..." line) would be the natural next
caller; not attempted this pass.

Verified: direct unit checks of `location_character_from_dicts` (a
mixed-axis case, an all-`None` case) and the `World`-scoped wrapper
still functioning identically; a 3000-tick LLM-disabled engine smoke
run, zero exceptions.

## [1.34.0] — A9: producer/consumer feedback-loop audit

Explicit user instruction: "tier 1 - 1" — `docs/ROADMAP-2026-07-
REMAINING.md`'s Tier 1 item 1, A9 ("feedback-loop audit — every
subsystem reads upstream AND writes downstream... likely finds real
gaps cheaply"). No such formal audit had been run before. Checked 15
state stores/subsystems named across CLAUDE.md and the roadmap doc
for a real producer AND a real downstream consumer.

Result: most are already genuinely closed loops (`FieldGrid.
population_density`, `HydrologyField.moisture`, `FarmGrid.soil_
fertility`, mineral veins, `ritual_activity`, `ruin_scars`, materials/
affordances feeding Innovation's prompt, memetics' propagation weight,
dialect/layout grammar, `InventedConcept.fitness_history`, `Agent.
immune_strength`, the one hand-authored `CompositeReaction`,
`Settlement.pattern_signal_counts` — no classic "increments counter Y
but the gate reads Z" typo bug found anywhere). Two real write-only
producers confirmed and fixed:

- **`World.mining_scars`/`World.disaster_scars`** had a real
  mechanical consumer for their two scar-dict siblings (`ruin_scars`
  biases build-site choice toward old foundations, `ritual_activity`
  boosts festivals) but had NONE themselves — a settlement's worked-
  out mines and disaster-struck ground were purely cosmetic/API-only.
  `Population._choose_build_site` now applies a real (soft, not a hard
  exclusion) penalty for both — badly scarred ground is measurably
  less attractive to build on, same shape as `ruin_scars`' existing
  positive pull but weaker and negative. New `MINING_SCAR_SITE_
  PENALTY_SCALE`/`DISASTER_SCAR_SITE_PENALTY_SCALE` (`world/terrain_
  evolution.py`, both 0.4, smaller than `RUIN_SITE_BONUS_SCALE`'s 0.6
  — a deterrent nudge, not a symmetric mirror of a positive pull).
  Threaded `mining_scars`/`disaster_scars` through `Population.tick`
  ->`_maybe_start_construction`->`_choose_build_site`, same shape as
  the existing `ruin_scars` threading; `world/state.py`'s call site
  passes both real dicts.

Recorded but NOT fixed this pass (real findings, each needs its own
scoped follow-up rather than a rushed fix inside an audit batch):
`world/spatial_memory.py`'s `location_character()` — the A19 read-side
unifier for exactly these scar dicts — is itself never called anywhere
(the audit's loudest flag: closing it properly would be the more
"correct" fix than the direct-dict-threading above, but this pass
took the cheaper, lower-risk path and left the unifier itself as a
still-open gap); `world/architecture_grammar.py`'s per-building
descriptor and `Settlement.legends` are both fully-formed producers
whose only reader is the JSON/API export (display-only, not a
downstream mechanical consumer); `llm/ontology.py`'s
`PRESSURE_SIGNAL_LABELS["materials_bottleneck"]` names a pressure
signal with no subsystem anywhere incrementing that key; `Agent.
genome` is confirmed write-once-at-birth only, never revised by lived
experience (unlike the genuinely bidirectional `immune_strength`
precedent this same codebase already has). Recorded in `docs/
ROADMAP-2026-07-REMAINING.md`'s A9 entry as concrete next items rather
than a vague "audit again later."

Verified: a 3000-tick LLM-disabled engine smoke run, zero exceptions.
`scripts/verify_native_soak.py` run (2 seeds x 1500 ticks) — confirmed
MISMATCH at tick 1055 reproduces byte-identically on unmodified
`origin/claude/hearthmind-overview-5bekay` (checked via `git stash`),
so it's a pre-existing native/fallback divergence unrelated to this
change, not a regression introduced here. `_choose_build_site` is pure
Python either way (never natively ported), and the new lookups are
plain deterministic dict reads with no RNG involved.

## [1.33.0] — Tier 0 second slice: a third real job for four pillars

Explicit user instruction: "continue with tier 0." Directly extends
v1.32.0's first slice — same additive mirror-into-`world_model`/
`memory` shape, four more pre-existing production jobs, zero new LLM
calls, zero mechanical changes:

- **Innovation** (now 3 jobs): `_maybe_schedule_ontology_evolution`
  (both the merge and evolve branches) mirrors the newly-registered
  concept as an `observation`, same treatment as `invention`.
- **Nature** (now 2 jobs): `_maybe_schedule_species_variant` mirrors a
  newly-named wildlife variant as an `observation` — a named variant
  is a settled fact about the land, same as `nature_mind`'s own
  belief-formation entries.
- **Village** (now 3 jobs): `_maybe_schedule_dispute` mirrors EVERY
  resolved dispute outcome (not just lasting ruptures) as a `remember()`
  note — a specific dispute between two named people isn't a
  settlement-wide theory, so this is memory-only, not `world_model`.
- **Humans** (now 3 jobs): `_maybe_schedule_migration_decision`
  mirrors a genuine departure decision as a `remember()` note —
  memory-only, same reasoning as `dream`: an individual's own choice,
  not a collective theory.

Verified via direct production-path smoke tests: `ontology_evolution`
and `species_variant` driven through their real gating conditions
(an `established` `InventedConcept`, an unnamed wildlife herd) with a
fake instant LLM client, confirmed correct `world_model` writes;
`dispute` driven through a forced-souring pair, confirmed the
`village_pillar.remember()` note; `migration_decision`'s empty-
candidate path confirmed non-crashing (the mirror line itself matches
the already-verified `dream`/`institution_belief` shape exactly — same
structure, no new risk). A separate unattended 3000-tick soak (fake
client, LLM "enabled") ran clean with zero exceptions. No native/
persisted-shape change, `verify_native_soak.py` not needed.

Coverage is now 2-3 jobs/pillar (was 1-2 after v1.32.0), still well
short of the ~55-job full refactor `docs/ROADMAP-2026-07-REMAINING.md`
names — none of these new sites participate in observe/interpret
cycling or attention-budget arbitration either, same open gap noted
in v1.32.0.

## [1.32.0] — Tier 0 first slice: widen pillar coverage beyond one job each

Explicit user instruction: "start with tier 0" (`docs/ROADMAP-2026-07-
REMAINING.md`'s own top-priority item — B1/B2/B3/B7 are each marked
"shipped" on the strength of exactly ONE representative production job
per pillar; the other ~50 LLM call sites in the codebase remain
untouched by the pillar abstraction). The full item names refactoring
all ~55 scattered jobs — genuinely too large for one batch, per the
roadmap doc's own note ("sequence it whenever a real multi-week push
is available, not as a quick follow-up"). This pass ships a real,
honest FIRST SLICE: one additional real production job per pillar
mirrors into that pillar's persistent `world_model`/`memory`, the same
shape `nature_mind` already established for Nature — doubling wired
coverage from 1 job/pillar to 2, not the full 55-job refactor.

New second job per pillar (all pre-existing, unchanged mechanically —
purely additive mirroring, zero new LLM calls):
- **Innovation**: `_maybe_schedule_invention` — an established
  invention is a settled fact, not a revisable theory, so it mirrors
  as `status="observation"` (confidence 1.0), distinct from ontology_
  proposal's `hypothesis` entries.
- **Reflection**: `_maybe_schedule_self_tuning` — a genuinely APPLIED
  governor nudge (sandbox-validated, not just proposed) mirrors as an
  `observation` too; a rejected/no-op nudge does not (nothing changed).
- **Village**: `_maybe_schedule_institution_belief` — an institution's
  own theory (FAMILY/COUNCIL/GUILD) is real Village-domain civic life,
  mirrored as a `hypothesis` alongside settlement-wide belief revision,
  tagged `source="institution_belief:<label>"`.
- **Humans**: `_maybe_schedule_dream` — deliberately memory-only, NOT a
  `world_model` entry: a dream is symbolic content, not a theory the
  collective holds (Phase G's ambiguity discipline stays intact).

Verified via direct production-path smoke tests (a `SimulationEngine`
built with `load_or_create` and a fake instant-responding LLM client,
same shape as the project's other ad-hoc verification scripts): each
of the four new mirror sites was driven through its own real gating
conditions (settlement prosperity for invention, a real `Institution`
member for institution_belief, a `supported` reflection hypothesis
naming a real `TUNABLE_GOVERNORS` key for self_tuning, the existing
monthly round-robin for dream) and confirmed to write the expected
`world_model`/`memory` entry with correct subject/belief/confidence/
source. A separate 4000-tick unattended soak (fake client, LLM
"enabled") ran clean with zero exceptions. `scripts/verify_native_
soak.py` not needed — no native module or persisted-field shape
touched, this only appends to fields the persistence layer already
round-trips generically.

Remaining ~50 job sites, B4/B8's one-sided gaps, and the full "acts of
five pillars" refactor stay open — recorded in `docs/ROADMAP-2026-07-
REMAINING.md`'s Tier 0 entry, unchanged; this is a slice of it, not a
close-out.

## [1.31.0] — Remaining-work roadmap: deep re-pass confirms completeness (docs only)

Explicit user request: "audit the master checklist deep pass and see
if there is anything else you have left out to implement and add that
to roadmap too."

Full verification pass: every `### A`/`### B`/`### C` heading in
`docs/MASTERCHECKLIST-2026-07-22.md` cross-checked 1:1 against `docs/
ROADMAP-2026-07-REMAINING.md`'s own section headings (all 25+9+5 = 39
items present); every "remain(s) open, flagged"/"NOT attempted"/"NOT
built" occurrence in the source doc located via direct search and
traced back to something already recorded in the roadmap — none
missing.

Two genuine findings added as a new "Addenda" section: (1) A11's R7
native-port deferral is justified differently than its neighbors
(weather/terrain-evolution/disasters are low-density; hydrology is
a from-scratch mechanism needing live shape-validation first) — worth
distinguishing before assuming it's next-in-line for the same reason.
(2) A loose thread in the SOURCE doc itself, not a code gap: its own
footer states the Humans-collective-vs-individual disagreement
question "needs an explicit user decision before step 14 ships," but
step 14 (B7) shipped in v1.12.0 by adopting the doc's own stated
default rather than a fresh confirmation — functionally resolved,
footer never updated to say so. No code action; optional doc
correction only.

## [1.30.0] — Remaining-work roadmap extended to Part B/C (docs only)

Explicit user follow-up: "add items from part B and C too why did you
not include it in the roadmap?" — a fair challenge to v1.29.0's own
scoping choice, which excluded Part B (the five-pillar Mind) and Part
C (the Body↔Mind seam) on my own judgment call, not something asked
for.

`docs/ROADMAP-2026-07-REMAINING.md` extended with full Part B (B1-B9)
and Part C (C1-C5) sections, same "quoted close to verbatim from the
Master Checklist" discipline as Part A. Real finding from actually
reading both sections in full: nearly every one of B1/B2/B3/B7 is
marked "shipped" on the strength of exactly ONE representative
production job per pillar — the other ~50 LLM call sites in the
codebase still run untouched by the pillar abstraction. Surfaced as a
new **Tier 0** ("the single biggest lever in the whole document") —
refactoring those scattered jobs into real acts of the five pillars is
bigger than any single Part A item and was previously undocumented as
a real, present gap. Other real B/C gaps folded into Tiers 2-3: B4's
one-sided disagreement classification, B5's now-actionable affordance/
reaction query (its Stage IV blocker has since shipped), B8's missing
reinforce/reinterpret, C2's mostly-unbuilt pillar-emitted-intention
coverage, C3's "pillars may initiate contact," and C4's missing
runtime auditor (only the review-time discipline exists today). B9 is
noted as effectively closed (B4 already covers its one named gap).

## [1.29.0] — Remaining-work roadmap filed (docs only)

Explicit user request: "build an updated roadmap to implement all the
features from all parts that you deferred for later and did not
implement in the first pass. This includes porting to C++ as well."

New `docs/ROADMAP-2026-07-REMAINING.md`: every "still open"/flagged
item across all 25 of Part A's det_sys.md items (docs/MASTERCHECKLIST-
2026-07-22.md), extracted close to verbatim so it stays a faithful
snapshot of the source doc, plus the R7 C++-porting backlog (per
CLAUDE.md's own standing note). A 4-tier priority ordering ranks items
by how many other open items they unblock and how directly they serve
emergence — Tier 1 (substrate: A9's feedback-loop audit, A11's
hydrology/erosion, A1's remaining fields, A2's diffusion operators)
through Tier 4 (standing review-time discipline: A23-25).

Scope stated explicitly in the doc rather than assumed: Part B (the
five-pillar Mind) and Part C (the Body↔Mind seam) are NOT re-swept —
per this project's own CLAUDE.md history, Stages I-III (steps 1-14)
are substantially shipped already, and re-auditing them wasn't judged
worth the length this pass would add. Same for other vision/audit docs
(docs/VISION-*, docs/IDEAS-2026-07-EMERGENCE.md, docs/AUDIT-2026-07-
20.md), each already marked resolved/historical elsewhere. Docs-only
pass, no code changes.

## [1.28.0] — A21 "Temporal compression," first slice — Stage IV fully closed

Explicit user instruction: "Start A21." A prior session's audit found
the obvious path blocked: `Settlement.folklore` entries carry only a
bare `{"tale": str}`, no structured subject a deterministic legend-
detector could match against without a fragile text heuristic.
Resolved by NOT touching folklore — new, separate pipeline reusing
A22's Emergence API stream instead, whose entries already carry a real
`subsystem` tag and `settlement` name.

New `world/legends.py`: `detect_legend_candidate` — deterministic,
zero LLM cost — scans `World.emergence_log`'s most recent entries for
a settlement, groups by `subsystem`, and returns a candidate once any
subsystem crosses `LEGEND_SUBSYSTEM_THRESHOLD=5` repeated observations
(and hasn't already produced a legend for this settlement — a simple
one-legend-per-subsystem-lifetime rule needing no extra state, since
`Settlement.legends`' own `subsystem` values ARE the "already
legendary" set). New `llm/legend.py`: narrates the accumulated pattern
into one legend sentence — "it's said that..." — distinct in both
content and cadence from folklore's monthly rumor-condensation.

New `Settlement.legends` (`SettlementCulture`, same passthrough-
property/to_dict/from_dict/summary wiring as `folklore`, capped at
`LEGENDS_MAX_STORED=16`). New `_maybe_schedule_legend_detection`
engine job, same monthly-rotation/backpressure/deterministic-first
shape as folklore/invention (most months resolve for free — no
subsystem has crossed threshold yet). UI: new "Legends" panel
(distinct from "Folklore"), `legend` (🐉) event-feed icon.

This closes Stage IV of the roadmap (docs/MASTERCHECKLIST-2026-07-22.
md) — all 16 originally-scoped steps now have at least a real first
slice shipped.

Explicitly NOT attempted this pass, flagged: folding a formed legend
back into tradition/religion/institution formation; using a legend as
grounding context in other prompts (chronicle/dialogue/folklore) the
way `place_names`/`beliefs` already ground other calls; any
unification with folklore itself.

Verified: direct smoke tests (`detect_legend_candidate`'s threshold/
already-legendary/settlement-filter logic, `llm/legend.py`'s prompt/
fallback/parse functions, `Settlement.legends` to_dict/from_dict/
summary round-trip), a 2000-tick real-engine run with seeded Emergence
API observations confirming the full detect -> LLM-schedule -> apply
-> `Settlement.legends` chain fires end-to-end, `node --check` on the
modified `app.js`, `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical — this pass touches only settlement-level Python
state, no native module.

## [1.27.0] — Live map field overlays + A20 extension (Stage IV close-out pass)

Explicit user instruction, follow-up to a live report ("I can't see the
hydrology implementation"): confirmed hydrology/soil-fertility/
population-density were real backend state (`World.hydrology_field.
moisture`, `FarmGrid.soil_fertility`, `World.fields`) with zero map
representation — only aggregate stat-tile numbers, or nothing at all.
User's explicit directive: "finish stage 4 and implement all part A
items to be visible on the live map itself. The map should change and
evolve with the simulation — that was the whole point."

New toggleable "🗺️ fields" header button cycles a live heatmap overlay
directly on the map canvas: off → soil moisture (A11, full per-tile
grid, blue tint) → soil fertility (sparse farmed-tile dict, amber-to-
green) → population density (A1/A20, coarse 3x3 region blocks, pink).
New `#field-canvas` layer between the base terrain and weather-particle
canvases. `interface/api.py`'s `set_terrain` gained `moisture`/`soil_
fertility`/`population_density` params, piggybacking on the existing
terrain-resync channel (same one `mining_scars`/`ritual_activity`/
`ruin_scars` already use) — `SimulationEngine._maybe_broadcast` now
also resyncs on a `week_end` calendar boundary specifically for these
three (none fire a `TERRAIN_CHANGING_CATEGORIES` event of their own),
plus a client-side 20s periodic re-fetch as a freshness guarantee that
doesn't require the frontend to understand calendar internals.

A20 "Multi-scale aggregation" (roadmap Stage IV step 29): the field-
visibility work exposed A1's `population_density` region field as
having exactly one consumer (`_maybe_favor_uncrowded_fission_site`) —
a thin claim for "multi-scale, cross-system state." New `MIGRANT_
DENSITY_DAMPENING` (`agents/population.py`): the same field now also
dampens migrant draw at an already-crowded settlement (`_maybe_
welcome_migrant`'s new `region_population_density` param, threaded
through `Population.tick`'s new `fields` param) — a genuine second,
independent consumer in a different subsystem, plus the field is now
directly visible on the map (see above). A brand-new second field and
"culture aggregates settlements' information-ecosystems" remain open,
flagged.

A21 "Temporal compression pipeline" (Stage IV step 30, the batch's
other requested item) explicitly NOT attempted: audited `Settlement.
folklore` and found entries carry only a bare `{"tale": str}`, no
structured subject/entity reference a deterministic legend-detector
could match against without a fragile text-heuristic. Flagged as
needing a real grounded-subject field on folklore/chronicle entries
first (its own follow-up), rather than shipping something half-built
under time pressure.

Verified: direct smoke tests (`set_terrain` payload shape/sizes,
`_maybe_welcome_migrant` with/without `region_population_density`), a
300-tick real-engine smoke run with the full `fields` → `Population.
tick` → `_maybe_welcome_migrant` chain live, `node --check` on the
modified `app.js`, `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical — the new consumer reads a deterministic float,
never touches the RNG call sequence.

## [1.26.0] — A3/A4 "Continuous procgen + scripted-event conversion," first slice (roadmap Stage IV step 28)

Explicit user instruction: "next step" — Stage IV step 28, docs/
MASTERCHECKLIST-2026-07-22.md's A3, whose own worked example is
"ruins should form where settlements die." Found the concrete gap by
reading `settlement/buildings.py`: `RUIN_REMOVAL_TICKS = 1200` deletes
a fully-decayed building with zero persistent trace once it's been a
ruin for ~12.5 sim-days — directly contradicting A3's own "a world
that looks different after a sim-year even with no humans" framing.

New `World.ruin_scars` (`world/terrain_evolution.py`'s `apply_ruin_
scar`/`decay_ruin_scars`, `RUIN_SCAR_GAIN_ON_REMOVAL=0.5`, `RUIN_SCAR_
DECAY_PER_WEEK=0.006` — by far the slowest of the four scar-shaped
dicts, ~1.6 years to fully clear): same shape as `mining_scars`/
`disaster_scars`/`ritual_activity` — a `World`-level sparse dict,
gained at both building-removal code paths in `Settlement.tick`
(native fast path and pure-Python fallback, both threaded a new
optional `ruin_scars` param), decayed weekly alongside the other three
in `World._tick_terrain`. Real consequence, not just a cosmetic mark:
`RUIN_SITE_BONUS_SCALE=0.6` biases `Population._choose_build_site`
toward a tile with a prior ruin — "the village rebuilds on old
foundations," a genuine callback loop between A3's own formation
mechanism and construction. Added as a 4th axis (`"ruin"`) to A19's
`world/spatial_memory.py` `location_character` unification. New
`building_reclaimed` life-event category added to `TERRAIN_CHANGING_
CATEGORIES` (both Python and JS sides) so the map overlay resyncs
immediately when a ruin scar is gained, no lag.

UI surfacing pass: new `paintRuinScars` map overlay (pale crumbled-
stone tint, distinct from mining/disaster/ritual), a "Ruins" main-UI
stat tile, and a bare-tile click-inspector "Ruins" line.

Deliberately scoped down from A3/A4's full spec: rivers re-carving via
elevation/erosion (needs mutating `Tile.elevation`, immutable and
native-store-backed — "the biggest remaining piece" per prior CLAUDE.md
notes) and A4's economy/agriculture/information continuous-field
conversion are explicitly NOT attempted this pass, flagged follow-up.

Verified: direct smoke tests (`apply_ruin_scar`/`decay_ruin_scars`
gain/clamp/decay math, `World.to_dict()`/`from_dict()` round-trip,
`location_character`'s new `ruin` axis, `_choose_build_site`'s ruin-
bonus site-selection bias on a synthetic fully-walkable grid,
`Settlement.tick`'s real removal-to-scar wiring on a synthetic
building), a 50-tick real-engine smoke run with the full `World.
ruin_scars` -> `Population.tick` -> `_choose_build_site` chain live,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
no native module touched, this pass is pure Python.

## [1.25.0] — A7 "Grammar-based procedural systems," first slice — three deterministic domains in one batch (roadmap Stage IV step 27)

Explicit user instruction: "next step" — Stage IV step 27, docs/
MASTERCHECKLIST-2026-07-22.md's A7, which the checklist itself flags
as needing a design decision resolved first: "which domains get
grammars vs. stay LLM-authored." Asked via `AskUserQuestion`: (1)
accept the doc's own default (layout/architecture/dialect
deterministic; myth/custom/law stay LLM, "they need meaning, not just
structure") — accepted as-is; (2) which ONE domain to ship first, same
"smallest coherent milestone" discipline as every other Stage IV step
— explicit user answer: "do everything," all three in one batch rather
than one.

New `world/dialect_grammar.py`: four deterministic rewrite rules
(vowel_shift, apocope, epenthesis, consonant_soften) over an EXISTING
LLM-coined term (`Settlement.lexicon` — the LLM still coins the
original term/meaning, `llm/narrative_direction.py`, unchanged).
`drift_term` picks a rule via a stable hash of the term text (never
`random` — a pure function, zero native-soak-parity risk) and, if the
chosen rule has nothing to act on for that specific term, tries the
rest of the four in a fixed rotation until one actually changes it
(rare full no-op: a term with no vowels and no soften-able consonant).
Real production consumer: `SimulationEngine._maybe_schedule_fission`'s
`apply()` — a daughter settlement now inherits `LEXICON_FISSION_DRIFT_
COUNT=2` of its origin's most recent terms, each independently
drift-mutated, instead of starting with an empty lexicon — "two
related villages now say things slightly differently," a real
emergent consequence of a real physical split.

New `world/layout_grammar.py`: `settlement_layout_style(settlement_id)`
picks one of `LAYOUT_STYLES = ("radial", "linear", "clustered")`
deterministically (stable for a settlement's whole lifetime — a pure
function of its own id). `layout_site_bonus` adds a real scoring term
to `Population._choose_build_site`'s existing road/resource-adjacency
scan — radial prefers a consistent ring-distance from the settlement's
center, linear prefers staying on one axis, clustered prefers hugging
already-standing buildings. Verified directly: the same founders'
position resolves to a genuinely different best build site with the
settlement's layout style applied vs. without it.

New `world/architecture_grammar.py`: `building_descriptor(building_id,
kind, material, layout_style)` — a three-slot production grammar
(roof/wall/ornament, each filled from a small closed vocabulary via a
stable per-building-id hash) generating ONE real distinguishing
sentence per building INSTANCE, not just per kind — closing a real gap
(`world/materials.py`'s existing "Built of" line reads identically for
every HUT of the same material). The roof slot is lightly biased
toward the settlement's own layout style ("a building echoes its
village's tradition") without ever fully determining it. Wired into
the live `buildings` broadcast payload (`SimulationEngine`'s per-tick
payload construction, alongside the existing `settlement_id`
computation).

UI: new "Layout" per-settlement stat tile (`Settlement.summary()`
gained `layout_style`, a pure computed field), a new "Character"
section in the building click inspector showing the per-instance
architecture descriptor.

Scoped down hard from the spec's own framing (L-systems/graph
grammars/production rules): none of the three is a full rewrite
system — layout is a scoring bias over the EXISTING site search, not a
graph grammar; architecture is a fixed three-slot production, not a
recursive shape grammar; dialect drifts one existing term per call,
not a generative lexicon. The spec's fourth named domain (ritual/
recipe structure) explicitly NOT attempted — it's closer to "meaning"
than "structure," the doc's own carve-out for staying LLM-authored.
Rules being themselves LLM-proposable (ties to Innovation) also not
attempted — every rule here is hand-authored, flagged in docs/
MASTERCHECKLIST-2026-07-22.md.

Verified: direct smoke tests for `drift_term` (determinism, the rule-
rotation fallback actually eliminating no-ops across a range of real
lexicon-shaped terms), `layout_site_bonus` (all three styles), `building_
descriptor` (determinism, distinct output per building id). A real
production-path test manually replaying the fission `apply()`'s exact
drift+validate logic against a live settlement's lexicon confirming
distinct daughter terms. A direct `_choose_build_site` call with vs.
without a settlement argument confirming the layout bonus genuinely
changes the chosen site. `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical — every new function is a pure, RNG-free
computation over existing state, so none of it can perturb the
existing RNG call sequence.

## [1.24.0] — A19 "Persistent spatial memory," first slice — a ritual-activity axis + read-side unification (roadmap Stage IV step 26)

Explicit user instruction: "next step" — Stage IV step 26, docs/
MASTERCHECKLIST-2026-07-22.md's A19: "every location accumulates a
bounded history vector... places gain *character* that influences
future simulation (a battle site stays scarred; a ritual site draws
ritual)." Status before this pass, the doc's own words: "`terrain_
activity`/`mining_scars`/`disaster_scars` track some per-location
history; not general" — three real dicts, but nothing read them
together.

New `World.ritual_activity`: a fourth per-tile dict, same additive-
overlay/weekly-decay shape as `mining_scars`/`disaster_scars`
(`world/terrain_evolution.py`'s new `apply_ritual_activity`/`decay_
ritual_activity`, `RITUAL_ACTIVITY_GAIN_PER_FESTIVAL=0.15`, `_DECAY_
PER_WEEK=0.01` — slower than the two scar axes, a site's standing
plausibly outlasts a worked quarry or scorched field). Gained when a
shrine-boosted festival gathering happens on a tile (`Population.
hold_festival`'s new optional `ritual_activity` param).

New `world/spatial_memory.py`'s `location_character(world, x, y)`:
the real read-side unification the spec calls for — one query over
the three existing per-tile dicts (mining/disaster/ritual), sparse
(only non-zero axes present). Deliberately NOT a new storage layer —
each dict stays exactly where it is, written by its own existing
mechanism; `location_character` is a read-only view. Scoped down hard
from the spec's full 9-axis vector (traffic/battles/pollution/
fertility/ownership/construction/ecology all remain separate or
unbuilt — `FarmGrid.soil_fertility`/the A1 field substrate are a
different shape, continuous fields not sparse per-event dicts, and
unifying them is real follow-up work, flagged in the module's own
docstring rather than silently attempted).

Real consequence, the doc's own worked example ("a ritual site draws
ritual") scoped to a buildable magnitude effect: a shrine tile that
has hosted a festival before amplifies the boost of the NEXT one held
there (`RITUAL_ACTIVITY_BOOST_SCALE=0.5` — up to 50% stronger at full
accumulated activity). Verified directly: two consecutive festivals at
the same shrine, second gain (0.161) measurably exceeds the first
(0.150) purely from the first festival's residual activity.

UI: new "Ritual sites" main-UI stat tile (same shape as "Mining
scars"/"Disaster scars"), a new golden-glow map overlay
(`paintRitualActivity`, piggybacking the existing terrain-resync
channel — flagged limitation: no dedicated resync trigger for a NEW
ritual site yet, so the overlay can lag until some OTHER terrain-
changing event fires a resync), and a "Ritual significance" line in
the SHRINE building click inspector reading the tile's own
accumulated intensity in plain language.

Verified: direct smoke tests for `apply_ritual_activity`/`decay_
ritual_activity` (gain/cap/decay-to-removal) and `location_character`
(sparse unification, absence-means-neutral), a real production-path
test driving `Population.hold_festival` through a live `SimulationEngine`
confirming the amplification effect, `World.to_dict`/`from_dict`
round-trip, a real-tick test confirming the weekly decay wiring fires.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical —
`ritual_activity` is a plain Python-side dict, same R7-deviation
rationale as `mining_scars`/`disaster_scars` (low-density tile lookup,
not yet worth a native port).

## [1.23.1] — Pillar cognition cold-start visibility (live-report follow-up)

Explicit live report: "Nature and especially Reflection still feel
disconnected from the actual simulation state. They are not forming
any hypothesis even after 13k ticks." Diagnosed (no code change to the
cadence itself — explicit user decision via `AskUserQuestion`: "Just
explain it, don't change code"): both jobs' B2 observe-then-interpret
cycle halves their already-slow season/year cadence, so the FIRST real
belief/hypothesis needs two boundary crossings, not one — ~17,520
ticks minimum for Nature (2 seasons), ~70,080 ticks minimum for
Reflection (2 years, and only if `_detect_reflection_pattern` finds a
real signal that cycle). At 13k ticks neither had a mathematical
chance yet. This was previously invisible; this pass makes it a
directly readable status instead of a silent wait.

New `Pillar.turns_processed`: a plain counter of real season/year
boundaries a pillar's cognition job has processed since creation
(bumped once per resolved observe OR interpret turn in `_maybe_
schedule_nature_mind`/`_maybe_schedule_reflection`, independent of
`cycle_stage`), persisted via `to_dict`/`from_dict` with legacy
backfill to 0. New `SimulationEngine._pillar_cognition_status()`:
computes a real live status for both pillars — stage (Observation/
Interpretation for Nature, Historical accumulation/Pattern analysis
for Reflection), boundaries observed vs. `PILLAR_COLD_START_
BOUNDARIES=2`, belief/hypothesis formation state, and (Reflection
only) whether `_detect_reflection_pattern()` would currently find a
signal. Deliberately placed in `full_diagnostics()` (on-demand `GET
/diagnostics` only), not the per-tick `_diagnostics_snapshot()` —
`_detect_reflection_pattern` scans every settlement's signal counts
plus up to `MAX_CONCEPTS_STORED` (400) invented concepts, the same
"don't compute every tick" reasoning `peak_memory_rss_mb`/`system_
memory` already follow.

UI: new "Pillar cognition status" panel in the dev console (`⚙ dev`),
populated when "Full diagnostic report" is clicked — a real formatted
block (not the usual raw-JSON dump), matching the explicit format the
user requested:
```
Nature
--------
Stage: Observation
Season boundaries observed: 1 / 2
Belief formation: Pending

Reflection
------------
Stage: Historical accumulation
Years observed: 0 / 2
Pattern detector: Not yet eligible
Hypothesis: Deferred
```

Verified: direct smoke tests of `_pillar_cognition_status()`'s initial
state and its transition after a real `_maybe_schedule_nature_mind`/
`_maybe_schedule_reflection` observe turn (via a live `SimulationEngine
.load_or_create` instance), `Pillar`/`World` round-trip (`turns_
processed` persists correctly), confirmed the field lives in `full_
diagnostics()` and NOT `_diagnostics_snapshot()`. `scripts/verify_
native_soak.py` (2 seeds x 800 ticks) byte-identical — `turns_
processed` is a plain Python-side pillar counter, no native module
touched.

## [1.23.0] — A18 "Events as composable reactions," first slice — a general AND-combination engine (roadmap Stage IV step 25)

Explicit user instruction: "Next step" — Stage IV step 25, docs/
MASTERCHECKLIST-2026-07-22.md's A18: "an event is a *reaction* fired
when a combination of field/social/economic conditions crosses a
threshold — not a scripted incident... a drought-field + a feud-edge
+ a food-shortage compose into [something] nobody hand-authored."

Deliberately distinct from `world/ontology.py`'s `TriggerRule` (a
SINGLE named trigger, LLM-authored per rule) — this is the doc's own
"small condition->consequence rule engine," where the combinatorial
part is real: three independently-tracked Body signals crossing their
OWN thresholds *simultaneously* compose into a consequence no single
condition would cause alone. New `world/reactions.py`: `CONDITION_
KEYS` (`drought`/`feud`/`food_shortage`, each backed by an already-real
or cheaply-computed signal — drought/food_shortage are edge-detected
the same heat_pressure/granary-fill readings `TriggerRule`'s `on_
drought`/`on_surplus` already use, just the opposite fill edge for
`food_shortage`; `feud` reads `Institution.feuds` directly),
`CompositeReaction` (an AND of `conditions`, matched via `matching_
reactions`). New `SimulationEngine._maybe_tick_composite_reactions`
(every tick, deliberately independent of `_maybe_tick_trigger_state_
edges` which early-returns with no stored `TriggerRule`s — a composite
reaction has nothing to do with village-authored rules): computes each
settlement's active condition set, checks it against the registry,
cooldown-gates (`COMPOSITE_REACTION_COOLDOWN_TICKS=1500`, longer than
a single `TriggerRule`'s 500 — a composite firing is a stronger event),
and applies via `_apply_composite_reaction`.

Scoped down hard, per this project's standing "first slice, not the
full spec" discipline: one hand-authored `CompositeReaction` ships
("Desperate Times": `drought` + `feud` + `food_shortage`), proving the
combinator itself works, not a general authoring system yet (a village
can't propose its own combinations the way `TriggerRule` is
LLM-authored — flagged follow-up). The doc's own worked example ("a
raid nobody hand-authored") is scoped down to a buildable, already-real
consequence rather than a new combat/raid mechanic: the two feuding
families' living members take a bounded, immediate relationship hit
(`COMPOSITE_REACTION_RELATIONSHIP_PENALTY=0.25`, smaller than a single
LLM-mediated dispute's own worst-case swing) plus a real Emergence API
`unexplained_shift` observation and a new `composite_reaction` event/
highlight entry.

UI: new `composite_reaction` event-log icon (💥) and filter-group
mapping (alongside `family_feud`/`dispute` under "people") — reuses the
existing event-log/highlights machinery rather than adding a new panel.

Verified: a real production-path test (manufactured two feuding FAMILY
institutions, forced `heat_pressure`/an empty granary to trigger
`drought`/`food_shortage`, called `_maybe_tick_composite_reactions`
directly) confirming the relationship penalty applies correctly, a
real `unexplained_shift` Emergence entry is appended, and the cooldown
correctly blocks an immediate re-fire. `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical — `_composite_reaction_last_
fired` is transient (same non-persisted precedent as `_prev_drought_
state`), no persisted field touched.

## [1.22.0] — A17 "Information ecosystem unification," first slice — social-graph-weighted propagation (roadmap Stage IV step 24)

Explicit user instruction: "Next step" — Stage IV step 24, docs/
MASTERCHECKLIST-2026-07-22.md's A17: "unify knowledge/rumor/tradition/
belief/song/map/custom/technique into one propagation model on the
social graph... each unit spreads... by the same rules."

Scoped down hard, per this project's standing "first slice, not the
full spec" discipline — the full unification is a large, genuinely
risky rewrite of several independent mature mechanisms (rumor
distortion, `invention_knowledge`'s teach/lose/rediscover, ontology
lineage) and is explicitly NOT attempted here. What ships: the one
piece every future propagation mechanism actually needs and none of
today's have — new `world/memetics.py`'s `propagation_weight`/
`weighted_spread_target`, a reusable "who catches this next" weighting
that traces the real relationship graph (`Agent.relationships`/
`.trust`, Phase 0's `Ledger`) instead of picking a next carrier
uniformly at random. A candidate's pull is the strongest single tie
among current carriers (`PROPAGATION_FONDNESS_WEIGHT=0.7`,
`PROPAGATION_TRUST_WEIGHT=0.3`, floored at 0 — an existing carrier who
dislikes a candidate exerts no pull, never a negative one) plus a
`PROPAGATION_BASELINE_WEIGHT=0.15` floor so word can still travel
beyond direct friendship, and so a concept with zero adopters yet
(empty `carriers`) degrades cleanly to uniform selection rather than
being unable to start spreading at all.

Real production proof: `SimulationEngine._maybe_spread_concepts`
(ontology concept adoption growth) previously picked a concept's next
adopter via a flat `rng.choice` over every eligible core-cast member
in the origin settlement, with zero regard for who was already an
adopter — a real gap against A17's own "propagation on the social
graph" framing, which had been true only of the docstring, not the
code. Now spreads via `memetics.weighted_spread_target(candidates,
carriers, rng)`, `carriers` being the concept's current living
adopters — a friend of an adopter is now measurably more likely to
pick up a new custom/technology next than a stranger is. Verified via
a direct distribution test (a candidate with a 0.95 fondness/0.8 trust
tie to the sole existing carrier was chosen ~55% of the time against 7
candidates, vs. ~14% under the old uniform pick) and a real production-
path test driving `_maybe_spread_concepts` itself through a live
`SimulationEngine`.

Deliberately NOT attempted this pass, flagged in docs/MASTERCHECKLIST-
2026-07-22.md: folding rumor/tradition/belief/song/technique spread
onto this same function, a shared mutate/decay/compete step, or "false
beliefs propagate if fit" (no fitness-vs-truth axis exists yet for
rumors) — `memetics.py` is the propagation-weight primitive the full
unification would need next, not the unification itself. No UI
surfacing this pass — this changes HOW an existing mechanism's next
adopter is chosen, not what state is exposed; concept adoption counts
were already reachable via the existing knowledge-tree panel.

Verified: a direct smoke test of `weighted_spread_target`/
`propagation_weight` (weighted pick skews correctly toward a strong
tie, degrades to uniform with no carriers, `None` on an empty
candidate list), a real production-path test exercising the actual
`_maybe_spread_concepts` engine method through a live `SimulationEngine
.load_or_create` instance. `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical — `memetics.py` touches only plain
Python-side agent/world state already covered by the soak's full
`World.to_dict()` comparison, no new persisted field.

## [1.21.0] — A14 "Layered organism biology," first slice — real immune state + full UI exposure pass (roadmap Stage IV step 23)

Explicit user instruction: "Next step" — Stage IV step 23, docs/
MASTERCHECKLIST-2026-07-22.md's A14, the spec's own worked example:
"immune response (illness resistance as state, not a coin flip)."
Followed immediately by an explicit user request mid-turn: "All these
new features should appear in the live map of UI as well, expose them
to UI" — addressed in the same batch (see the UI section below), not
deferred.

New `Agent.immune_strength`: a real continuous 0..1 state, plain
Python-side (not native-store-backed, same as `traits`/`genome` —
zero parity risk). `Population._tick_immune_strength` (every tick, all
agents): hunger/energy pull it toward a nutrition/rest-derived target
via exponential smoothing (`IMMUNE_ADAPT_RATE` — a real physiological
lag, not instantaneous like hunger/energy themselves); an active
infection drains it further (`SICKNESS_IMMUNE_DRAIN_PER_TICK`, the
reverse coupling — fighting illness taxes the immune system). `_tick_
disease` now multiplies both `SICKNESS_TRANSMISSION_CHANCE_PER_TICK`
and the per-tick death-chance roll by `_immune_modulation_factor`,
stacking with (never replacing) the existing resilience/medicine/
hospital modifiers. Centered so `IMMUNE_BASELINE=0.5` is a true no-op
against every already-tuned sickness rate — the modulation only ever
pushes rates up or down from the well-calibrated center that existed
before this system, never silently re-tunes the baseline.

Scoped to the ONE subsystem the spec names explicitly (immune
response); stress, reproduction, development/life-stages, injury-
recovery, and sleep — the other five named subsystems — remain open,
explicitly flagged rather than silently folded into this slice. A
genetic contribution to baseline immune_strength (beyond nutrition/
rest) is a real, flagged future connection to A15 (v1.20.0), not built
here.

**UI exposure pass** (explicit user request, this same batch): audited
every feature shipped across the last several roadmap steps (18-23)
for real main-UI/map visibility, not just dev-console/NPC-inspector
reachability:
- `World.summary()` (the regular per-tick broadcast, not `full_
  diagnostics()`'s dev-console-only payload) now includes a real
  `discoverable` field per settlement — the same A5/A6/A12/A13 query
  Innovation's own proposal prompt already grounds on, computed live
  from standing buildings. New "Discoverable" main-UI stat tile
  aggregating combinations/reactions across all settlements.
- Agent map markers gained a third status ring: a faint amber ring
  when `immune_strength` is notably low (run down from nutrition/rest
  neglect) but not currently sick/recently-immune — visually distinct
  from the existing starving/sick/immune rings, a real glanceable
  "this person is vulnerable" signal on the live map itself.
- NPC inspector's health line (`healthLabel`) and Personality section
  gained plain-language immune-state readings ("healthy, but run
  down" / "immune constitution: robust/steady/run down").
- Genetics (A15) and evolutionary innovation (A8) were confirmed
  already reaching real UI (NPC inspector's "mixed inheritance" line,
  knowledge-tree's "generation N" marker) — no gap found there.

Verified: direct tests for `_tick_immune_strength` (nutrition/rest
pull in both directions, sickness drain, floor clamping, average-
hunger/energy staying at baseline) and `_immune_modulation_factor`
(exactly 1.0 at baseline, bounded, correct direction at extremes);
`Agent.to_dict`/`from_dict` round-trip including legacy backfill to
`IMMUNE_BASELINE`; a 3000-tick real production-path engine run
confirming genuine population-wide immune_strength drift; a full
`World.to_dict`/`from_dict` round trip; a direct `World.summary()`
test confirming the new `discoverable` field. `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical, re-run after both the
population.py/agent.py changes and the state.py UI-exposure change. A
Node syntax check confirmed the app.js edits parse cleanly.

## [1.20.0] — A15 "Genetic inheritance," first slice, scoped to humans (roadmap Stage IV step 22)

Explicit user instruction: "Next step" — Stage IV step 22, docs/
MASTERCHECKLIST-2026-07-22.md's A15. Direct target: `_inherited_
traits`'s own docstring already confessed "Trait inheritance is
blend+noise (v0.87-era), not genetics" — exactly this doc's own
Status line for A15.

Replaces v0.87.6's flat parent-average-plus-Gaussian-noise trait
blend with real diploid genetics. New `Agent.genome: dict[trait,
(allele_a, allele_b)]` over the four existing psychology axes
(resilience/sociability/ambition/openness) — `Agent.traits` (the
phenotype every existing trait-consuming call site already reads,
completely unchanged in meaning) is now the mean of its two alleles,
so zero downstream code needed to change.

Inheritance (`Population._inherited_genome_and_traits`, replacing
`_inherited_traits`): for each trait axis, a child's allele from each
parent is independently drawn from THAT parent's own two alleles (real
genetic drift — which allele passes on is random, not an average) and
independently subject to `GENOME_MUTATION_CHANCE` of instead being
replaced by a fresh mutated value (`GENOME_MUTATION_STDDEV`) — real
Mendelian-style recombination + mutation, not the old deterministic
blend. A parent with no recorded genome (any pre-A15 agent) is treated
as "homozygous at its current phenotype," so inheritance stays total
even from a genome-less parent — never a crash or a silently-skipped
axis. `TRAIT_INHERITANCE_MUTATION_STDDEV` kept as a historical record,
no longer read by any code.

Founders (`Population.spawn_initial`/`spawn_successor_founders`) now
draw a real diploid genome at spawn (`agent.seed_founder_genome`,
`GENOME_FOUNDER_ALLELE_STDDEV`) — every prior founder started flat 0.0
on all four axes (traits were "never rolled at spawn, only earned via
lifetime event nudges," per `TRAIT_INHERITANCE_MUTATION_STDDEV`'s own
old docstring); this closes that as a real, verified side effect
(founder resiliences now spread genuinely, e.g. -0.43 to +0.43 in one
12-founder test run) rather than a separate fix.

*Natural selection* (the doc's third named mechanism, "differential
survival/reproduction from real fitness") needed no new code: these
four traits already causally affect survival/reproduction odds
(H6/"traits mechanically consumed, not write-only" — resilience's
starvation-tolerance and predator-death-chance influence, sociability's
role in reproduction pairing) — genetics gives that PRE-EXISTING
selection pressure a real heritable substrate to act on for the first
time, rather than adding a second, parallel, redundant fitness
mechanism. This is called out explicitly rather than silently assumed.

Scoped deliberately to humans only. Wildlife/animal genetics (the
doc's "species adapt over generations... no authored progression"
half, and domestication as selective pressure from humans) remain
open — `world.wildlife.SpeciesVariant` (Vision item 4.2) stays
descriptive-only, not wired to a genome, for the same `AnimalHerd`
native-index parity-risk reason it was originally deferred. A14
("Layered organism biology," physiological genes beyond the existing
psychology-trait axes) is a real prerequisite for a fuller genome and
also remains open. `Organism.genome: ndarray` (the spec's literal data
model) was deliberately not used — a `dict[str, tuple[float, float]]`
matches the existing trait-axis shape exactly, with no numpy
dependency needed for four scalar pairs.

UI: NPC inspector's Personality section gained a plain-language "carries
a mixed inheritance in ..." line when an agent's alleles for a trait are
notably divergent (a real reading of the underlying genome, not raw
allele numbers) — reachable wherever the existing trait display already
is, no new panel needed.

Verified: direct tests for `seed_founder_genome` (covers all four
axes, values bounded), `_agent_allele_pair` (genome present/absent/
neither), `_inherited_genome_and_traits` (bounded output, `traits`
genuinely the mean of the returned `genome` alleles), a 2000-trial
statistical test confirming ~93% of inherited alleles trace to an
actual parental allele at the default mutation chance (matching
`1 - GENOME_MUTATION_CHANCE`), `Agent.to_dict`/`from_dict` round-trip
including legacy-snapshot backfill to `{}`, `spawn_initial` producing
real founder trait variance. A 6000-tick real production-path engine
run (LLM disabled) observed a real birth and inspected its genome
directly. A full `World.to_dict`/`from_dict` round trip confirmed
genome persistence (within the existing 4-decimal rounding convention
every other float field already uses). `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical — `genome`/`traits` are plain
Python-side agent state, never native-store-backed, so this carries
zero parity risk by construction, confirmed anyway.

## [1.19.0] — A8 "Evolutionary Innovation loop," first slice (roadmap Stage IV step 21)

Explicit user instruction: "Next step" — Stage IV step 21, docs/
MASTERCHECKLIST-2026-07-22.md's A8. `world/ontology.py` already had
propose/evolve/merge with a real lineage DAG (*generate*); this closes
the loop with a real *evaluate* + *select* pass — concepts now spread
AND retire by evaluated survival, not adoption count alone.

*Evaluate*: `evaluate_fitness(world, concept)` — the doc's own "did
adopters prosper?" — reads as the mean `Population.reputation` (Phase
L, already-existing, already-cached monthly) of a concept's currently-
LIVING adopters, relative to its origin settlement's living-population
mean reputation. Returns `None` (not a faked 0.0) when there's nothing
real to measure (no living adopters, or no living settlement members).

*Select*: `run_selection(world, tick)`, paired at the exact same
monthly cadence/call site as the existing `abandon_stale` sweep. Every
`spreading`/`established` concept gets one fresh fitness reading
appended to a bounded `fitness_history` (`FITNESS_HISTORY_MAX=8`,
skipped not zero-padded when unevaluable). Only once at least
`FITNESS_EVALUATION_MIN_READINGS=3` real readings exist does sustained
mean fitness below `FITNESS_UNFIT_THRESHOLD=-0.05` retire the concept
(`status = "retired"` — a new, distinct terminal state from
`abandoned`: this concept DID catch on for a while, unlike a stale
`proposed` one that never adopted at all) and revise Innovation's own
mirrored world-model belief about its hypothesis, same mechanism
`abandon_stale` already uses. `retired` concepts join `abandoned` ones
as the first tier `prune_concepts` clears when `MAX_CONCEPTS_STORED`
is exceeded.

The real consumer wiring: `fit_established_concepts`/`concept_fitness_
weight` make `_maybe_schedule_ontology_evolution`'s evolve/merge parent
pick a genuine fitness-WEIGHTED draw (via `random.choices`) instead of
a flat-uniform `rng.choice` — a concept with a real positive mean
fitness reading is measurably more likely to become a parent, closing
the spec's own "fit concepts spread and become parents" framing. An
un-evaluated or mildly-below-average `established` concept is never
categorically excluded (floored weight 0.1) — real evolutionary
diversity, not a hard cutoff duplicating `run_selection`'s own
retirement bar. `InventedConcept` gained `generation` (0 for an
original proposal, `max(parents) + 1` for evolve/merge, threaded
through `register_concept`'s new param) — `parent_ids` itself needed
no new field, already covered by the existing `lineage` DAG.

Scoped down from the spec's full generate→mutate→evaluate→select
description: sandbox forward-simulation (`simulation/sandbox.py`,
A-C) as a fitness input, and grammar-based mutation (A7) as a second
*generate* path alongside LLM propose/evolve/merge, are real, larger
follow-ups, explicitly flagged rather than attempted. Every concept
category (technology/custom/law/ritual/saying/profession/institution_
flavor/ecological) goes through the same mechanism — farming
techniques/governance/customs weren't singled out for special
treatment, matching how `InventedConcept` was already category-
agnostic.

UI: knowledge-tree entries for a concept with `generation > 0` now show
a "generation N" marker in the same lineage-bits slot as "evolved
from"/"merged from" — reachable in the existing 🌳 panel, no new UI
surface needed.

Verified: direct tests for `evaluate_fitness` (positive/negative
signal, no-living-adopters, no-settlement-members), `run_selection`
(sustained-unfitness retirement, history cap, neutral-fitness-stays-
established, proposed/abandoned concepts never evaluated),
`concept_fitness_weight`'s neutral/positive/floored-negative cases,
`fit_established_concepts`' status filter, `register_concept`'s new
`generation` param, and full `InventedConcept.to_dict`/`from_dict`
round-trip (including legacy-snapshot backfill to 0/empty-list) plus a
`World`-level `to_dict`/`from_dict` round trip. A 1500-tick real
production-path engine run (LLM disabled) completed with no error; a
direct `knowledge_tree()` test confirms the generation field surfaces
correctly. `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical, re-run after both the ontology.py changes and the
state.py/knowledge_tree() change.

## [1.18.0] — A13 "Chemistry / reaction system," first slice (roadmap Stage IV step 20)

Explicit user instruction: "Next step" — Stage IV step 20, docs/
MASTERCHECKLIST-2026-07-22.md's A13, the direct continuation of A12
(v1.17.0) — "material science + chemistry together are the 'invent
metallurgy without hardcoding metallurgy' engine."

New `world/chemistry.py`: exactly the doc's own three worked examples,
reinterpreted against A12's real `MATERIALS` registry — `clay` + `heat`
→ `ceramic`, `ore` + `heat` → `metal`, `fiber` + `water_and_time` →
`cured_fiber` (fiber tanning/curing, the real-world "plant + water +
time" process the doc names). `world/materials.py`'s `MATERIALS`
registry gained three new entries backing these: `ore` (metal's raw,
harder-to-work, less-conductive precursor), `ceramic` (fired clay —
harder, far more durable, zero flammability, but far less workable),
`cured_fiber` (tanned/cured fiber — notably more durable and decay-
resistant than raw fiber). Every reaction product is a real, fully-
propertied `Material` like any other — a discovered reaction product
is immediately `derive_affordances`-capable, not a special second-class
output type.

`discover_reactions(available_materials, present_affordances)` is the
real "what does X produce under Y?" query the doc names — conditions
(`heat`/`water_and_time`, closed vocabulary) are themselves derived
from the SAME A5/A6/A12 affordance layer step 18/19 already built
(`can_conduct_heat`/`can_burn` imply `heat`; `can_carry_water` implies
`water_and_time`), so a settlement genuinely needs both the right
material present AND the right kind of building standing, not a flag
set by hand.

Scoped down from the spec's literal `ReactionRule(reactants,
conditions, products, rate)` + "a deterministic reactor that fires
rules when conditions meet" (an automatic tick-loop mechanism that
would mutate world state) — this ships the QUERY half only, same
"query first, automatic effects later" scoping A5/A6 itself took with
its own validate-step deferral. A real reactor changing a standing
building's material after the fact needs its own design pass (what
would that even change mechanically?) — explicitly flagged, not
attempted.

Real consumer, wired exactly like A5/A6's `discoverable_combinations`:
`_maybe_schedule_ontology_proposal` computes standing-building
materials/affordances (reusing the same query already built for step
18/19) and passes `discover_reactions`'s result into `llm/ontology.py`'s
`build_propose_prompt` (new optional `discoverable_reactions` param).
New dev-console `discoverable_reactions` diagnostic, same shape/depth
as `discoverable_affordance_combinations`.

Verified: direct tests for `world/chemistry.py` (every rule's reactant/
product/condition resolves against real closed vocabularies,
`available_conditions`'s heat/water_and_time derivation from
affordance tags, `discover_reactions` for each of the three worked
examples individually and in combination, the "material present but
no condition" negative case). A direct test of `build_propose_prompt`'s
new param. A 400-tick real production-path engine run (LLM disabled)
completed with no error; a direct `_diagnostics_snapshot()` test
confirms a SHRINE (clay) + FORGE (heat-capable) settlement surfaces
`ceramic` as discoverable. `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical.

## [1.17.0] — A12 "Material science / physical properties," first slice (roadmap Stage IV step 19)

Explicit user instruction: "Next step" — Stage IV step 19, docs/
MASTERCHECKLIST-2026-07-22.md's A12, the direct continuation of v1.16.0's
A5/A6 — "affordances start deriving from properties rather than being
hand-tagged."

New `world/materials.py`: `Material` (all ten spec-named properties —
hardness, density, conductivity, elasticity, durability, decay_rate,
flammability, toxicity, thermal_capacity, workability — each 0..1) and
a small closed `MATERIALS` registry: wood, stone, clay, metal, fiber.
Hand-authored (not measured), same discipline as A5's hand-tagging,
with real-world-plausible relative ordering (stone harder/denser/less
flammable than wood; metal most conductive; fiber most flammable-and-
workable-but-least-durable) — the ordering is what makes derivation
below produce sensible output, not literal material-science accuracy.
`BUILDING_MATERIALS` assigns each of A5's tagged `BuildingKind`s its
primary material, grounded in each kind's own existing docstring
identity (wood huts/docks, stone forges/bridges, worked metal at a
forge/factory/power-plant, fiber at pasture/hatchery fencing, clay at
the shrine).

The real bridge: `derive_affordances(material)` maps property
thresholds to a subset of `world.affordances.AFFORDANCE_TAGS`
(hardness+workability → `can_sharpen`; flammability → `can_burn`;
conductivity OR thermal capacity → `can_conduct_heat`; hardness+density
→ `can_support_weight`; toxicity → `can_poison`) — deliberately
partial, since `can_store_food`/`can_carry_water`/`can_redirect_water`/
`can_fertilize` are shape-derived, not raw-material-derived, and this
function only ever derives what genuinely follows from material
properties alone. New `building_affordances(kind)` is the real union
point: `world.affordances.BUILDING_AFFORDANCES`'s existing hand-tagged
set PLUS whatever the assigned material derives — hand-tagging never
disappears, it's extended.

Real consumer: `_maybe_schedule_ontology_proposal` (Innovation's A5/A6-
wired generate-step, v1.16.0) now computes standing-building
affordances via `materials.building_affordances` instead of the bare
hand-tagged set, so a genuinely material-driven combination (e.g. a
metal FORGE's `can_conduct_heat` following from conductivity, not just
a hand tag) is reachable by the proposal prompt too. The dev-console
`discoverable_affordance_combinations` diagnostic (v1.16.0) widened the
same way.

Scoped down from the full spec: per-instance `Entity.material:
Material` (every tool/vehicle/agent-crafted good carrying its own
material, not one closed per-`BuildingKind` lookup) and A13's
chemistry/reaction system (`A + B + condition → C` over these
properties) are real, larger follow-ups, explicitly flagged rather
than attempted.

UI: building click inspector gained a "Built of" line (client-side
`BUILDING_MATERIAL` mirror of `BUILDING_MATERIALS`, same mirroring
precedent as `daylight.py`'s `UK_DAYLIGHT_HOURS`) — plain
environmental fact, not Phase-G-gated.

Verified: direct tests (every `BUILDING_MATERIALS` entry resolves to a
real registered material; every `derive_affordances` output stays
within the closed vocabulary; metal derives `can_conduct_heat`/
`can_sharpen`, fiber derives `can_burn` but not `can_support_weight`,
stone derives `can_support_weight` but never `can_burn`;
`material_for_building` known/unknown; `building_affordances` always a
superset of the hand-tagged set, and empty for an untagged kind). A
400-tick real production-path engine run (LLM disabled) completed with
no error; a direct `_diagnostics_snapshot()` test confirms a standing
FORGE now surfaces both `tempered_tools` and `kiln_process`.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## [1.16.0] — A5/A6 "Affordances + discovery query layer," first slice (roadmap Stage IV step 18)

Explicit user instruction: "Next step" — Stage IV step 18, docs/
MASTERCHECKLIST-2026-07-22.md's A5/A6, the prerequisite the doc itself
names for Innovation to discover unprogrammed combinations rather than
only ever naming within its existing closed hook vocabulary.

New `world/affordances.py`: `AFFORDANCE_TAGS`, the exact closed
vocabulary named in det_sys.md's own A5 example (`can_burn`,
`can_shelter`, `can_carry_water`, `can_sharpen`, `can_store_food`,
`can_redirect_water`, `can_fertilize`, `can_poison`,
`can_support_weight`, `can_conduct_heat`). `BUILDING_AFFORDANCES`
hand-tags `BuildingKind` — deliberately the "wrap, don't replace"
path the spec itself names: `BuildingKind` stays exactly as it is (a
closed enum mirrored into the C++ native store's integer code
tables — unsafe to touch mid-run), this attaches an ADDITIONAL,
purely-Python, purely-additive tag-set as external data. Each tag
reflects something that kind's existing identity/mechanics already
imply (a GRANARY already `can_store_food` per its own docstring; a
FORGE's description already invokes heat and tools).

A6's query layer: `affordances_present(standing_kinds)` — "what here
can_X?" — and `discover_combinations(present_tags)` — "what
combination of affordances would achieve Y?" — over a small, closed
`KNOWN_COMBINATIONS` registry (5 entries, e.g. `can_carry_water` +
`can_store_food` → `irrigation_store`, `can_conduct_heat` +
`can_sharpen` → `tempered_tools`). A combination surfaces only when
both its required tags are genuinely present among a settlement's
actually-standing buildings — deterministic, not LLM-asserted.

Real consumer, wired into Innovation's generate-step per the spec's
own "Feeds" line: `_maybe_schedule_ontology_proposal` now computes the
settlement's standing-building affordances and passes `discover_
combinations`'s result into `llm/ontology.py`'s `build_propose_prompt`
(new optional `discoverable_combinations` param) — the proposal prompt
is now grounded in real physical capability alongside (not replacing)
the existing prosperity/pressure-signal grounding. The validate-step
half named in the spec (re-checking a PROPOSED concept's claimed
mechanism against this layer, the way `validate_hook` already
re-verifies skill/goal targets) is explicitly NOT attempted this
pass — flagged follow-up; this slice covers the harder, more novel
generate-step half.

Also scoped down from the full spec: `Entity.affordances`/`Entity.
properties` as genuine PER-INSTANCE fields (any entity, not just
buildings) and A12's material-property registry (affordances DERIVED
from properties rather than hand-tagged) are real, larger follow-ups,
not attempted. This pass is a class-level `dict[BuildingKind,
frozenset[str]]` over the one entity class with an existing real
foundable/standing lifecycle to ground a proposal in.

New dev-console diagnostic: `full_diagnostics()`'s per-tick snapshot
gained `discoverable_affordance_combinations` (per settlement, live-
computed, not persisted state) — same depth as `invented_concepts_by_
category`.

Verified: direct tests for `affordances_present`/`discover_
combinations` (aggregation across multiple standing kinds, an
untagged kind contributing nothing, empty input, the exact-tag-pair-
subset requirement, deterministic sort order) and every `BUILDING_
AFFORDANCES`/`KNOWN_COMBINATIONS` tag confirmed to stay within the
closed `AFFORDANCE_TAGS` vocabulary; a direct test of `build_propose_
prompt`'s new param (grounding text present/absent). A 400-tick real
production-path engine run (LLM disabled) completed with no error, and
a direct `_diagnostics_snapshot()` test confirms the new field
computes correctly against real standing buildings.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## [1.15.0] — A10 "Ecology as interacting populations / food webs," nutrient cycling (roadmap Stage IV step 17)

Explicit user instruction: "Next step" — Stage IV step 17, docs/
MASTERCHECKLIST-2026-07-22.md's A10. Scoped down from the full A10
spec (migration, competition, decomposition, nutrient cycling,
pollination, habitat formation, folding the food web onto the A1 field
substrate) to a single well-justified first slice: nutrient cycling
into farming, per the doc's own explicit "Feeds: nutrient cycling
closes a loop into farming" line.

New `economy/farms.apply_nutrient_cycling(farms, herds)`: any
`FarmGrid.soil_fertility`-tracked tile (i.e. a tile that's ever been
farmed) within `NUTRIENT_CYCLING_RADIUS=2` (Manhattan) of a
`WildlifeGrid` herd gains a small per-tick fertility bonus scaled by
`herd.count * NUTRIENT_CYCLING_BONUS_PER_ANIMAL`, summed across every
nearby herd but capped at `NUTRIENT_CYCLING_MAX_BONUS_PER_TICK` per
tile per call (several large overlapping herds can't instantly max a
tile out) and by the existing 1.0 fertility ceiling — real grazing/
dung enrichment, bounded the same way `SOIL_FERTILITY_MIN`/`_RECOVERY_
PER_TICK` are already bounded. Called from `World._tick_disasters` on
`"week_end" in calendar_events`, same cadence as A11's `tick_hydrology`
and the same reasoning: bound the real-time cost of a full-grid-
adjacent Python pass rather than running it every tick.

Deliberately a standalone module function, not a `FarmGrid`/
`WildlifeGrid` method: reads `WildlifeGrid.herds` read-only, writes
only into tiles already present in `soil_fertility` (never expands the
tracked-tile set), and never touches either grid's native fast path
(`_native_farm_grid_tick`, `_native_soil_fertility_deplete_step`/
`_recover_step`, or the wildlife grid's native-ported grazer branch) —
zero native/fallback parity risk by construction, still confirmed via
the soak run below. Migration, competition, decomposition (as a
distinct nutrient source beyond live-herd enrichment), pollination, and
habitat formation are explicitly NOT attempted this pass — real,
larger follow-ups, flagged in docs/MASTERCHECKLIST-2026-07-22.md's A10
section rather than silently dropped; the "fold the existing food web
onto the A1 field substrate into one coupled system" framing item also
remains open.

UI: new "Soil fertility" main-UI stat tile (`summary.farms.avg_soil_
fertility`, already computed, previously unsurfaced) — plain
environmental state, not Phase-G-gated, tooltip explains both the
existing fallow-recovery mechanic and the new nutrient-cycling bonus.

Verified: direct tests for `apply_nutrient_cycling` (no-op on an
untracked tile, in-radius bonus, out-of-radius no-effect, clamp to
1.0, the per-tick max-bonus cap actually engaging with several large
herds, and the exact Manhattan-radius boundary). A real production-
path test drives a real `SimulationEngine`/`World` through ~8 real
week boundaries with a large herd parked on a previously-depleted
farmed tile, confirming `soil_fertility` measurably rises (0.3 -> 0.81
over the run) beyond what ordinary fallow recovery alone would give
it. `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical.

## [1.14.0] — A2 "CA/diffusion/reaction-diffusion operators" (roadmap Stage IV step 16)

Explicit user instruction: "Next step" — Stage IV step 16, docs/
MASTERCHECKLIST-2026-07-22.md's A2.

New `world/ca_operators.py`: a small library of generic, pure field
operators, per det_sys.md's own spec — `diffuse(grid, rate)` (spread
toward neighbor average — heat, moisture, scent), `reaction_diffuse(a,
b, rate_a_to_b, rate_b_to_a)` (two coupled fields exchange value,
conserving mass at each cell), `cellular_step(grid, rule)` (the
generic Conway-style per-cell rule, `rule(own_value, neighbor_values)
-> new_value`). Each is a pure function over any `list[list[float]]` —
not tied to `world/fields.py`'s coarse 3x3 `FieldGrid`, so any future
full-resolution field can compose them, matching the spec's own
"a per-tick pipeline lists which run in what order."

Forest succession — det_sys.md's own worked example, "the first
consumer" — is real, not a demo: new `terrain_evolution.compute_
succession_pressure` builds a 0/1 forest-tile indicator grid, runs it
through `diffuse` to get a genuine smoothed "how forested is my
neighborhood" reading (not just a flat 4-neighbor count), and averages
it against A11's real per-tile moisture field (v1.13.0's `Hydrology
Field`) — a direct "systems interacting with existing systems" tie-in,
not an isolated new field. The result MODULATES `_tick_fallow`'s
existing `REFOREST_MIN_FALLOW_WEEKS` threshold per tile: a well-
forested, moist neighborhood can reclaim in as few as `SUCCESSION_
WEEKS_MIN=1` week; a poor one can take up to `REFOREST_MIN_FALLOW_
WEEKS * SUCCESSION_WEEKS_MAX_MULTIPLIER` (2x) — bounded both
directions, real det_sys.md "gated by ... moisture" behavior.

Deliberately a MODULATION of the existing, already-tuned reclaim rate,
not a wholesale replacement — `maybe_reclaim`'s reforest-CHANCE roll
has a native C++ fast path (`_native_maybe_reclaim_tick`); rewriting
that mechanic outright would have real regression risk on a live-tuned
number. The eligibility computation this pass touches (`_tick_fallow`)
stays pure Python regardless of which path the chance-roll takes, so
native/fallback parity is structurally unaffected — confirmed by the
soak run below. `moisture=None` (a caller without a hydrology field,
or an old test) keeps the original flat-threshold behavior exactly,
verified directly.

Verified: direct tests for all three operators (`diffuse`'s spread
and no-op-at-rate-0 behavior, `reaction_diffuse`'s mass conservation,
`cellular_step`'s neighbor-rule application), `compute_succession_
pressure`'s moisture-sensitivity, `_tick_fallow`'s flat-rate backward
compatibility (unchanged when `succession_pressure` is omitted) and
its modulated fast/slow paths (a well-forested+moist tile reclaims
faster than the flat rate; a sparse+dry one reclaims slower), and a
real production-path test through `maybe_reclaim`'s actual native-vs-
fallback dispatch. A 700-tick full-engine run (LLM disabled) completed
with no error. `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical.

## [1.13.0] — A11 "Continuous hydrology," first slice (roadmap Stage IV step 15 — starts Stage IV)

Explicit user instruction: "Start Stage 4's first step" — the first
step of Stage IV ("Deepen the Body," 16 steps), docs/MASTERCHECKLIST-
2026-07-22.md's A11, the roadmap's own "highest-leverage single item."

The existing `world/hydrology.py` only ever answered "is this tile a
river or a lake" — rivers carved once at genesis, lakes with their own
slow bounded-random-walk level. What A11 actually asks for is water as
a genuinely CONTINUOUS field every tile carries, with real flow and
feedback into agriculture/siting/disasters/ecology. Given the size of
the full spec (four real pieces: flow, groundwater, evaporation,
erosion-into-mutable-elevation), this ships a real, working first
slice rather than attempting all four at once — the same "scoped first
version, deferrals flagged explicitly" discipline every Stage III step
this session used.

New `world/hydrology_field.py`: `HydrologyField`, a real per-tile
0..1 `moisture` grid. `tick_hydrology` runs three real passes each
week: precipitation gain (scaled by `WeatherState.precipitation`),
a single-pass downhill transfer (each land tile pushes a bounded
fraction of its above-neighbor moisture excess to its lowest-elevation
orthogonal neighbor, computed against a snapshot so no tile's transfer
depends on iteration order), and evaporation (faster in summer). Water-
biome tiles stay pinned at full saturation. Two of A11's four pieces
are explicitly NOT attempted and flagged rather than silently dropped:
groundwater (no subsurface reservoir layer — surface moisture only)
and erosion feeding back into now-mutable elevation (`Tile.elevation`
stays immutable this pass — the single biggest remaining piece of
A11, deliberately deferred since it touches the already-native-ported
`TerrainGrid` and needs its own careful equivalence pass).

Real consumers, not a number nothing reads: `FarmGrid.plant()` gained
a `moisture` param (new `FARM_MOISTURE_YIELD_MIN_FACTOR=0.5` floor —
a bone-dry tile still yields half of a fully-watered one's potential,
never zero) threaded from `Population._maybe_plant`/`Population.tick`
through `World.tick`'s existing `population.tick(...)` call site,
reading `World.hydrology_field.moisture` at the exact tile a field is
planted on — a planting decision's real yield now genuinely depends on
local water, not just soil fertility. New `SimulationEngine._detect_
hydrology_drought` (Emergence API, edge-triggered like `_detect_
settlement_bottlenecks`): a genuinely widespread drought (>=50% of all
tiles below `HYDROLOGY_DROUGHT_THRESHOLD=0.15`) emits one `bottleneck`
observation tagged `nature`/`village`, silent while it persists or once
it recovers.

R7 deviation, flagged (docs/CONSTITUTION.md's "new physical-substrate
code is C++-first" rule): ships in pure Python, weekly cadence (not
per-tick, to bound the real-time cost of an un-ported full-grid pass),
not yet natively ported. Justification, explicit: this is a genuinely
NEW field-based mechanism, not a reimplementation of an existing
pattern the way mining_scars/soil_fertility were — the flow-
accumulation algorithm's exact shape needs to prove itself against
real gameplay before being locked into a compiled interface expensive
to iterate on further. Port to C++ once the shape is confirmed live,
following `cpp/src/soil_fertility.cpp`'s precedent exactly.

New silent-backfill persistence: `World.hydrology_field` gets a fresh
field via `create_hydrology_field(terrain)` when loading a pre-A11
snapshot — deliberately NOT routed through the `migrated_subsystems`
narrative-announcement machinery (rivers/lakes use that since they're
one-time genesis events a player would notice being added); a
background field silently rebuilding is the same treatment
`_biome_counts_cache` already gets.

Surfaced: `World.summary()["hydrology"]["avg_moisture"]`, a new "Soil
moisture" stat tile in the main UI (average moisture as a percentage)
— explicitly player-facing per the standing workflow rule, not
dev-console-only, since it's plain environmental state like weather.

Verified: direct tests for `create_hydrology_field`/`tick_hydrology`
(water-tile saturation, moisture rising under sustained rain, falling
under sustained drought, round trip), `FarmGrid.plant()`'s moisture-
scaled yield (wet vs. dry vs. default-unset backward compatibility),
a real production-path test driving the actual weekly tick through
`SimulationEngine._tick_once` and confirming the field visibly changes,
`World.to_dict`/`from_dict` round trip including legacy-snapshot silent
backfill, and the drought detector's edge-trigger discipline (fires
once on the falling edge, doesn't re-fire while still in drought,
clears silently on recovery). `scripts/verify_native_soak.py` (2 seeds
x 800 ticks, long enough to cross a real week boundary) byte-identical
— the new field only mutates inside `World.tick`'s deterministic
weekly branch, exercised identically by both native and fallback runs
since nothing in this pass touches a native-ported module.

This starts Stage IV. 15 steps remain (16-30); per the roadmap's own
scoping note, each is a substantially larger effort than any single
Stage I-III step — continuing only on explicit future direction naming
the next step, same standing convention as every other vision doc.

## [1.12.0] — B7 "Humans collective consciousness + coordinator," first version (roadmap Stage III step 14 — closes Stage III)

Explicit user instruction: "Continue with next roadmap" — Stage III
step 14, docs/MASTERCHECKLIST-2026-07-22.md's B7, the last of Stage
III's 5 steps.

Audit first: both mechanisms this item names already existed. "One
collective mind (mood/values/direction)" is `humans_pillar` itself —
`_maybe_schedule_narrative_direction`'s own docstring already reads
this as "B7's collective consciousness read literally," since
`Settlement.mood` is the real aggregate of every living agent's
`Agent.emotions`. "A capped pool of cheap per-NPC calls on
dramatically-salient individuals" is core-cast cognition
(`Population.core_agent_ids`, bounded by `llm_core_cast_size`) plus
the voice pair's own narrative-significance selection (`Population.
maintain_voice_pair`) — also already real. The genuine gap: these two
mechanisms ran entirely unaware of each other. `SimulationEngine`'s
voice-pair-rotation call site logged a `voice_pair_change` event but
never told the collective mind anything — Humans' `self_model` had no
record of who currently carries the village's voice, and the rotation
never reached the Emergence API, so the collective mind's own
`observe` turn had no way to perceive it.

Fixed: the rotation site now writes `humans_pillar.self_model[
"current_protagonists"] = [name_a, name_b]` directly (zero LLM cost —
Humans' own persistent record of its current salient individuals, per
B9's self-model framing) and emits a real `"opportunity"`-kind,
`humans`-tagged Emergence API observation, so a rotation reaches the
collective mind's next real `observe` turn as perceived context,
exactly like any other pillar's genuine news already does. This
doc's own standing design decision (§"Two flags before building":
"when the Humans collective consciousness and an individual NPC
disagree, who speaks... individual acts locally, collective sets the
mood/direction they're measured against") is respected structurally —
`current_protagonists` is the collective's own AWARENESS of who's
salient, never a channel that speaks or acts on an individual's
behalf; the individual voice pair still speaks for itself via the
existing dialogue machinery, untouched.

`default_humans_pillar()`'s seeded `self_model` gained a
`"current_protagonists": []` default key so every fresh world starts
with the field present and empty rather than absent until the first
rotation.

Surfaced: dev-console-only (`full_diagnostics()["humans_pillar"]`),
matching every other pillar's internals — the rotation itself already
had real main-UI visibility via the pre-existing `voice_pair_change`
event log entry, so no new panel was needed for this pass's actual
delta.

**This closes Stage III of the roadmap** — all 5 steps (10 C3, 11 B4,
12 B5, 13 B6, 14 B7) are now shipped, each a real, scoped first
version. Stage IV ("Deepen the Body," 16 steps) remains open.

Verified: a direct engine-level test drives the actual voice-pair-
rotation call site through a real multi-tick run (LLM disabled),
confirming `Population.voice_pair_ids` gets selected, `humans_pillar.
self_model["current_protagonists"]` is populated with the real
selected names, and a matching `humans`-tagged Emergence API
observation is appended — the full real production path, not an
isolated unit test. `Pillar.self_model`'s `to_dict`/`from_dict` round
trip re-verified with the new key present. `scripts/verify_native_
soak.py` (2 seeds x 500 ticks) byte-identical — the new writes only
occur inside the existing tick-loop voice-pair-maintenance call site
(itself deterministic and already exercised identically by both
native and fallback runs), never inside an async apply() callback or
any native-ported path.

## [1.11.0] — B6 "Reflection as meta-scientist," first version (roadmap Stage III step 13)

Explicit user instruction: "Continue with next roadmap" — Stage III
step 13, docs/MASTERCHECKLIST-2026-07-22.md's B6.

Root gap: `_maybe_schedule_self_tuning` matched a supported reflection
hypothesis's subject against `self_tuning.TUNABLE_GOVERNORS` by EXACT
equality against only two hardcoded global labels ("wildfire
frequency", "ontology coherence"). But `_detect_reflection_pattern`'s
other five signal families (materials bottleneck, dispute feud,
starvation death, disease outbreak, wildlife recolonization, nature
adaptation) all produce SETTLEMENT-scoped subjects
(`f"{label} in {settlement_name}"`) — these could never match a fixed
dict key regardless of what governor existed, so a real, evidence-
backed, supported hypothesis about any of them was silently dropped
every single time, with no response at all.

Fixed with two pieces, matching the roadmap item's own two asks.
First, "extend TUNABLE_GOVERNORS to the major levers": new
`SimulationEngine._governor_key_for_subject` matches a hypothesis
subject against `TUNABLE_GOVERNORS` by PREFIX (`subject.startswith
(label)`), not exact equality — this alone makes every settlement-
scoped pattern reachable, not just the two subjects that happened to
be global. `TUNABLE_GOVERNORS` gained a real worked example for this
path: `"disease outbreak" -> "disease_outbreak_chance"`, consumed by a
new `chance_multiplier` param on `Population._maybe_outbreak` (applied
to the base per-tick chance, before the existing small-settlement
floor, which stays a real guarantee regardless of any governor nudge)
— `World.governor_tuning.get("disease_outbreak_chance", 1.0)` is
threaded through `Population.tick`'s call site in `world/state.py`
exactly like the existing `wildfire_chance` wiring. `_maybe_outbreak`
is ordinary per-tick Python logic, not native-ported, so this carries
no native/fallback parity risk (unlike wildlife/predator mechanics,
which stay untouched this pass for exactly that reason).

Second, "add the human-reviewed advisory-proposal inbox (human-
reviewed) for changes beyond governors": a supported hypothesis that
STILL names no governor (even after the prefix-matching fix) is no
longer silently skipped — `SimulationEngine._schedule_advisory` fires
a real, `critical=True` LLM call (`llm/self_tuning.py`'s new
`SYSTEM_PROMPT_ADVISORY`/`build_advisory_prompt`/`fallback_advisory`/
`parse_advisory`) asking Reflection for one short, free-text piece of
advice grounded in the hypothesis, logged into new `World.advisory_
proposals` (`{id, tick, hypothesis_id, subject, advice, status}`,
`status` starting `"pending"`). New `POST /advisory/{id}/review`
(`{status: "accepted"|"rejected"}`) — routed through the existing
`_apply_intervention` seam via a new `review_advisory` kind and
`SimulationEngine._review_advisory` — is the ONLY way that status ever
changes; nothing auto-applies an advisory to any real mechanic, kept
strictly out-of-band from the sandboxed, bounded numeric self-tuning
path that governors still use. "Track whether its advice worked" is
deliberately NOT attempted as a further automated measurement — there
is no mechanical effect from an advisory to score an outcome against
(unlike a governor nudge, whose real multiplier IS the measurable
thing); the human's own accepted/rejected marking on `POST /advisory/
{id}/review` is itself the tracked outcome, not a placeholder for one.

Both `self_tuning_actions` (governor path) and `advisory_proposals`
(advisory path) are checked together for "already acted on this
hypothesis" (`acted_hypothesis_ids` now unions both lists) so the same
supported hypothesis can never trigger both an LLM job types across
different firings. Surfaced: `advisory_proposals_recent` (last 10) in
`full_diagnostics()`, same dev-console-only depth as `self_tuning_
actions_recent` — this is Reflection's own internal record, not a
player-facing feature, matching Phase G/self-tuning's existing
precedent.

Verified: direct tests for the new prefix-matching helper, the
advisory prompt/fallback/parse layer, the outbreak-multiplier wiring
(a `chance_multiplier=0.0` smoke test), and `World.advisory_proposals`/
`next_advisory_id`'s `to_dict`/`from_dict` round trip including legacy-
snapshot compatibility. Two real production-path tests (monkeypatched
fake LLM client) exercise `_maybe_schedule_self_tuning`'s actual apply()
end to end: one showing a settlement-scoped `"disease outbreak in
Elmswick"` subject now correctly reaches the governor path via prefix
match and applies a real bounded nudge; one showing a subject with no
matching governor (`"predator pressure"`) correctly takes the advisory
path instead, and that `POST /advisory/{id}/review`'s intervention
dispatch correctly updates its status. `scripts/verify_native_soak.py`
(2 seeds x 500 ticks) byte-identical — `_maybe_outbreak`'s multiplier
only ever differs from 1.0 inside an async self-tuning apply() callback,
never inside `_tick_once`'s deterministic path, and stays 1.0 (a true
no-op) on every soak run since no governor tuning is ever applied there.

## [1.10.0] — B5 "Innovation as conscious scientist," first version (roadmap Stage III step 12)

Explicit user instruction: "Continue with next roadmap" — Stage III
step 12, docs/MASTERCHECKLIST-2026-07-22.md's B5. The doc's own item
names its full scope (query the Stage IV affordance/reaction layer)
but explicitly permits "a first version against today's closed-hook
vocabulary" — that's what ships here.

Root gap: `_maybe_schedule_ontology_proposal` already gated itself on
whether the settlement was "pressured" (any `Settlement.pattern_
signal_counts` value crossing `PATTERN_SIGNAL_BELIEF_THRESHOLD`) but
never told the LLM WHICH pressure was live — a proposal made under
real strain was invented exactly as freely as one made purely from
prosperity, so no genuine hypothesis was ever possible even when the
gate had already fired on a specific problem.

Fixed with two pieces. First, grounding: the engine now computes the
dominant crossed signal (max value among `pattern_signal_counts`,
e.g. `materials_bottleneck`, `dispute_feud`) and passes it to `llm/
ontology.py`'s `build_propose_prompt` as `pressure_signal`, rendered
in plain language via a new `PRESSURE_SIGNAL_LABELS` table ("a
shortage of building materials," "a run of bitter disputes and
feuding," ...). The model is now explicitly told: if a problem was
named, treat your idea as a real hypothesis for it — a guess that
might be wrong; if nothing was named, it's free to just be culture for
its own sake. Second, a real `hypothesis` JSON field (parsed/validated
same as every other field, "no specific problem" normalizes to an
empty string — a legitimate value, not a missing one) is stored on
`InventedConcept.hypothesis`.

The scientist half — closing the loop, not just naming a claim once —
is `world/ontology.py`'s new `_record_hypothesis_outcome`: the
concept's mirrored entry in `World.innovation_pillar.world_model`
(its id captured at proposal time as the new `InventedConcept.
world_model_entry_id`) gets REVISED IN PLACE (`revises_id`, not a new
entry) when the concept's real adoption lifecycle later confirms it
(`add_adopter` promotes it to `established` — confidence raised to
0.85, status `observation`) or refutes it (`abandon_stale`'s existing
stale sweep marks it `abandoned` — confidence dropped to 0.1). Zero
added LLM cost: the outcome is read straight off state that already
exists (`status`, `adopter_ids`), not asked of the model a second
time. A concept with no hypothesis (or, defensively, no captured
`world_model_entry_id`) is a correct no-op — nothing to confirm or
refute. This is the concrete "an idea is a testable guess, and the
Innovation pillar tracks whether its own guesses actually panned out"
mechanism the doc's "conscious scientist" framing asks for, scoped to
the registry Innovation already has (not waiting on Stage IV's
affordance/reaction substrate, which doesn't exist yet).

UI: `World.knowledge_tree()`'s existing concept entries now append the
hypothesis as plain-language context ("... (a hopeful answer to: a
response to a shortage of building materials)") when one exists — real
value in the already-shipped 🌳 knowledge-tree panel, no new panel
needed since nothing else consumes this field yet.

Deliberately NOT attempted this pass: evolve/merge (`_maybe_schedule_
ontology_evolution`) stay unchanged — hypothesis-tracking wasn't
extended to them; and any real query against affordances/reactions,
since that substrate is Stage IV, not built. Both flagged as the
re-targeting this item's own text anticipates once Stage IV lands.

Verified: direct tests for the confirm path (adopters -> established
-> confidence 0.85/status observation), the refute path (stale sweep
-> abandoned -> confidence 0.1), the no-hypothesis no-op, `InventedConcept.
to_dict`/`from_dict` round trip including legacy-snapshot compatibility
(old dicts missing the two new fields load with correct defaults), and
the prompt/fallback/parse layer's hypothesis wiring (pressure_signal
grounding text, "no specific problem" normalization). A real
production-path test (monkeypatched fake LLM client) exercises `_maybe_
schedule_ontology_proposal`'s actual apply() end to end, confirming the
hypothesis and `world_model_entry_id` land on the registered concept
and the mirrored belief starts at 0.4/`hypothesis` as before.
`scripts/verify_native_soak.py` (2 seeds x 500 ticks) byte-identical —
the new mechanism only runs inside async LLM-job apply() callbacks and
the existing monthly `abandon_stale`/`add_adopter` calls, never inside
`_tick_once`'s deterministic native-ported path.

## [1.9.0] — B4 "Inter-pillar consciousness bus" (roadmap Stage III step 11)

Explicit user instruction: "Next step" — Stage III step 11, docs/
MASTERCHECKLIST-2026-07-22.md's B4. The five pillars' `inbox`/`outbox`/
`MESSAGE_KINDS`/`make_message()` (`cognition/pillar.py`) had existed
structurally since B1 (v1.5.0) but were never actually delivered
between pillars — this ships real typed-message delivery, making a
pillar's `inbox` a genuine second input channel alongside the
Emergence API.

`Pillar.send_message`/`receive_message` (bounded `OUTBOX_MAX`/
`INBOX_MAX=8`, oldest dropped past cap — same discipline as `working_
memory`/`conversation_log`). New `Pillar.disagrees_with(subject_text)`:
a real mechanical definition of disagreement — does the pillar already
hold a confident (`>=0.5`) `world_model` theory whose `subject` label
substantially overlaps the incoming subject, via exact substring
containment or Jaccard word overlap (`word_overlap()`, new module-level
helper) at or above `DISAGREEMENT_OVERLAP_THRESHOLD=0.2`. Comparing
short `subject` labels rather than full belief sentences was a
deliberate correction made during development: an initial version
compared full sentence text at a 0.3 threshold and a direct test showed
two genuinely-related but independently-phrased sentences ("drought and
water scarcity" vs. "The land is drying, water grows scarce.") overlap
at only ~0.1 word-for-word — nowhere near enough to ever fire. Subject
labels ("drought") are short and directly comparable, so the switch
plus a lower threshold makes the check actually reliable against real
LLM-authored phrasing, verified via both isolated tests and a real
production-path test (monkeypatched fake LLM call) confirming correct
`"disagreement"` vs. `"warning"`/`"observation"` classification.

`SimulationEngine._send_pillar_message(from, to, kind, summary, data)`
constructs a message via `make_message` and delivers it into both
sides' outbox/inbox. Three concrete arrows wired at existing apply()
call sites, each gated on a genuinely new belief/concept (not every
tick): **Nature -> Village** (`_maybe_schedule_nature_mind`, kind is
`"disagreement"` when `village_pillar.disagrees_with(subject)`, else
`"warning"` at confidence >=0.6, else `"observation"`); **Village ->
Innovation** (`_maybe_schedule_beliefs`, kind `"theory"`, confidence
>=0.5 gate); **Innovation -> Village** (`_maybe_schedule_ontology_
proposal`, kind `"discovery"`, fires on every newly registered
concept). Reflection's "observes all four Minds" arrow needed no new
code — `_detect_reflection_pattern` already reads every pillar's Body
state directly, a one-way read not a message. The reverse disagreement-
aware classification (Village/Innovation checking whether the SENDER
disagrees) is flagged as a follow-up — only the Nature->Village site
does real disagreement classification this pass.

`_pillar_observe_turn` (the B3 salience scheduler) now merges
undelivered `inbox` messages into the SAME magnitude-ranked candidate
pool as Emergence API observations, via a new `_PILLAR_MESSAGE_
MAGNITUDE` table giving each message kind a synthetic magnitude
(`disagreement` 0.9 highest, down to `observation` 0.45) — a
disagreement message competes for and usually wins one of the five
`working_memory` slots on a pillar's next observe turn. Only messages
that actually get delivered this turn are removed from `inbox`; an
outranked message survives to compete again next cycle — this is the
literal mechanism behind "disagreement persists" rather than being
silently dropped or unconditionally force-fed regardless of priority.

Verified: direct tests for `send_message`/`receive_message` bounds,
`disagrees_with`'s subject-comparison correctness (substring + Jaccard
paths, both true/false cases), the inbox-merge/delivery/survival logic
in `_pillar_observe_turn`, a full `to_dict`/`from_dict` round trip with
an undelivered message surviving persistence, and a real production-
path test (monkeypatched fake LLM client) exercising `_maybe_schedule_
nature_mind`'s actual apply() showing correct message-kind
classification end to end. `scripts/verify_native_soak.py` (2 seeds x
500 ticks) byte-identical — message delivery only occurs inside async
LLM-job apply() callbacks, never inside `_tick_once`'s deterministic
native-ported path.

## [1.8.0] — C3 "Player <-> Pillar chat" (roadmap Stage III step 10)

Explicit user instruction: "Start [Stage] 3's first step" — the first
of Stage III's 5 steps, docs/MASTERCHECKLIST-2026-07-22.md.
Generalizes the existing Ask-the-Chronicler pattern (settlement-scoped,
narrative-only) to any of the five cognitive pillars.

New `llm/pillar_chat.py`: one shared `SYSTEM_PROMPT_TEMPLATE` (not five
hand-written prompts) — each pillar's answer is voiced through its own
`self_model["voice"]`/`description`, so Nature "never speaks as a
person" while Reflection "proposes hypotheses, never asserts
certainty" without maintaining five near-duplicate prompt strings.
Answers are built ONLY from the pillar's own real `objectives`/
`world_model`/`memory` — same "never a ground-truth readout dressed up
as in-character text" discipline the chronicler already holds.

`Pillar` (`cognition/pillar.py`) gained `conversation_log` (bounded,
`CONVERSATION_LOG_MAX=10` — "a light per-pillar player-model"),
`last_question`/`last_answer`/`last_answer_tick` (persisted), `pending`
(not persisted, same "in-flight state never survives a restart" reason
as `World.chronicler_pending`). New `GET /pillar/{pillar}`/`POST /ask/
{pillar}` (`interface/app.py`) and `SimulationEngine._schedule_pillar_
answer`, same enqueue-now/apply-next-tick seam as `_schedule_
chronicler_answer`.

"Nudges enter cognition as weighable inputs, never commands" (the
checklist's own phrasing): the resolved Q&A exchange is written into
`working_memory` via `note_observation()` — the SAME list every
representative pillar job's real `interpret` cognition call already
reads via `emergence_observations=list(world.<pillar>_pillar.working_
memory)` (the B2 mechanism). A recent question genuinely reaches that
pillar's next real cognitive turn as one more thing it noticed,
exactly like a salient Emergence API observation would — there is no
path from a player's question to a direct belief write or a bypassed
decision. "Pillars may initiate contact" (the checklist's own stretch
goal) is explicitly NOT attempted — flagged as real future scope.

UI: a new "🗣 ask a pillar" panel (pillar-select dropdown + question
form) under the explore menu, mirroring the existing chronicler panel
— per the standing workflow rule, this is explicitly player-facing
(Stage III's own title), not dev-console material.

Verified: direct engine-level test of the full `ask_pillar` ->
`_schedule_pillar_answer` -> apply -> `Pillar` state round trip
(pending clears, conversation recorded, working_memory updated,
`World.summary()["pillars"]` reflects it, `to_dict`/`from_dict`
survives with `pending` correctly resetting to `False`); an unknown-
pillar/blank-question no-op test; `scripts/verify_native_soak.py` (2
seeds x 400 ticks) byte-identical (a real-time-request-driven feature,
no change to the deterministic tick path).

## [1.7.1] — C1/C2 seam wiring (roadmap Stage II step 9)

Explicit user instruction: "Build step 9." Part C of docs/
MASTERCHECKLIST-2026-07-22.md ("THE SEAM") asks for the perception
channel (C1, Body → Mind) and intention channel (C2, Mind → Body) to
be made real for whichever pillars exist. Both were mostly already
real by construction once B1-B3 generalized to all five pillars — this
pass audited both against their exact spec wording and closed the two
real gaps found.

**C1 "bounded, salience-ranked, pillar-tagged"**: bounded (`Pillar.
WORKING_MEMORY_MAX=5`) and pillar-tagged were already true for every
pillar since B2. "Salience-ranked" was not — `_pillar_observe_turn`
fed pillar-tagged candidates from the 40-entry Emergence API window
into `working_memory` in plain recency order, so the FIFO cap could
silently discard a genuinely high-`magnitude` observation in favor of
a later, less salient one purely because it logged first. Fixed:
candidates are now sorted by `magnitude` (descending, unranked-`None`
sorted last) before only the top `WORKING_MEMORY_MAX` are noted — a
pillar's small attention budget is now deliberately spent on what
matters most this turn.

**C2 "every pillar acts only by emitting intentions the Body
validates and executes"**: audited every Body-touching write across
all five representative jobs. Village (`beliefs`) and Reflection
(`reflection`) write only their own Mind-state (theories/hypotheses),
never Body — nothing to validate, correctly. Innovation (`ontology_
proposal`) and Nature (`nature_mind`'s ecological-concept origination)
already validate before writing (`ontology.validate_hook`/`is_near_
duplicate`). Humans (`narrative_direction`'s dialect-drift term
coining) was the one real gap: it created a brand-new persistent
`Settlement.lexicon` entry with only a non-blank/length check, no Body-
side validation at all. New `narrative_direction.validate_coined_
term()` rejects an exact case-insensitive duplicate of an already-
coined term before the write — same discipline `validate_hook` already
enforces for Innovation. The spec's broader action list (invent tech,
set custom, change law, reorganize institution, shift land use,
domesticate, build, propose experiment) mostly isn't pillar-emitted at
all yet — those remain separate deterministic/LLM mechanics outside
the five-pillar refactor's current reach, correctly flagged PARTIAL
rather than force-completed.

Verified: direct smoke test of `_pillar_observe_turn`'s salience
ranking (mixed-magnitude/mixed-order candidates → top-5-by-magnitude
selected, unranked entries sorted last); direct `validate_coined_term`
test (duplicate rejected case-insensitively, novel term accepted);
`scripts/verify_native_soak.py` (2 seeds x 400 ticks) byte-identical.

## [1.7.0] — Symmetric idle speedup + B8 Living memory & consolidation (roadmap Stage II step 8)

Two explicit user requests in one turn: "the adaptive slowing of the
simulation should also adaptively speed up the simulation when LLM
load is low and system is sitting idle," and "continue the roadmap."

**Idle speedup.** `_llm_pressure_interval_multiplier()` (`simulation/
engine.py`) previously only ever stretched the real-time gap between
ticks (>= 1.0x) as LLM backlog pressure rose — a genuinely idle queue
(a fresh world, a quiet stretch, or `llm_enabled=False` entirely) ran
at exactly the user's configured/selected speed regardless of how much
spare LLM/CPU capacity was sitting unused. New `LLM_PRESSURE_SPEEDUP_
START_RATIO=0.15`/`LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER=0.4` mirror the
existing slowdown shape on the low side: below a pressure ratio of
0.15 (comfortably under the existing slowdown band's own 0.75 floor,
so there's a real flat "just right" zone at 0.15-0.75 that behaves
exactly as before), the multiplier scales linearly DOWN to 0.4 (up to
2.5x faster ticks) as the ratio approaches 0. Faster ticks mean agents
become cognition/dialogue-due sooner in real time (staggered-daily
eligibility is tick-count-based, the same mechanism the slowdown side
already leans on in reverse), converting idle LLM capacity into more
calls per real second rather than a merely cosmetic faster clock.
Purely a function of the existing `llm_pressure_ratio()` — no new
"is the system idle" signal needed, since an idle queue (including
`llm_enabled=False`) already reads as ratio 0.0 by construction. New
`full_diagnostics()["llm_pressure_interval_multiplier"]` surfaces the
live value (<1.0 sped up, 1.0 normal, >1.0 slowed) for the dev console.

**B8 — Living memory & consolidation, all five pillars** (docs/
MASTERCHECKLIST-2026-07-22.md, roadmap Stage II step 8). New `Pillar.
consolidate()` (`cognition/pillar.py`): once a pillar's `memory` list
reaches `MEMORY_CONSOLIDATE_THRESHOLD` (30, comfortably under the
existing hard `MEMORY_MAX=40` FIFO safety-net cap), folds the oldest
`MEMORY_CONSOLIDATE_BATCH` (8) raw notes into ONE condensed digest note
instead of letting them sit until the blind evict-oldest cap silently
drops them. Real forgetting (the individual raw notes are gone, not
merely capped) plus a literal form of "connect into concepts" (several
granular notes become one higher-level one) — deliberately zero LLM
cost, matching "maximize emergence per LLM call" (a genuine LLM-
authored summarization would be a real future upgrade, not this pass's
scope). Wired into the shared `SimulationEngine._pillar_close_cycle`
helper (already called once per closed cognitive cycle for all five
pillars since the B1-B3 generalization pass), so every pillar gets
real periodic consolidation automatically with no per-pillar wiring.
Deliberately NOT `reinforce`/`reinterpret` (the rest of B8's spec) —
that needs per-note salience/access tracking this pass doesn't add,
flagged as a smaller follow-up. Also updates the roadmap doc: B9
("self-model & world-model per pillar") is retroactively marked
SHIPPED — it was effectively subsumed by the earlier B1-generalization
pass (self_model/world_model have been part of `Pillar`'s shape for
every pillar since v1.5.0/v1.5.3), not a separate step as the roadmap
originally implied.

Verified: direct smoke test of `_llm_pressure_interval_multiplier()`
across idle/mid-zone/saturated backlog states (0.4x / 1.0x / 6.0x as
expected); a direct `Pillar.consolidate()` test (35 notes → fold to
28, correct digest content, no-op below threshold); `scripts/verify_
native_soak.py` (2 seeds x 400 ticks) byte-identical (both changes are
either real-time-pacing-only or a pillar-memory operation neither soak
harness's deterministic `_tick_once()` path exercises differently).

## [1.6.0] — Per-fallback diagnostics + single-adapter model-agnostic LLM layer

Explicit multi-part user request: (1) diagnose why `personal_belief`'s
`deep_reasoning=True` calls were still falling back so heavily; (2)
expose `raw_model_output`/`parsed_json`/`validation_errors`/`fallback_
reason`/`fallback_result` in the dev console whenever ANY LLM call
falls back; (3) refactor so adding a new LLM backend requires
implementing exactly one adapter class, with simulation/cognition/
prompts/validation/memory/game-logic staying completely model-
agnostic; (4) re-confirm Nemotron 3 Nano 4B as the default and tune the
adapter specifically around it.

**Root-cause finding for (1)**: `personal_belief` (`llm/beliefs.py`'s
`PERSONAL_SYSTEM_PROMPT`) asks for by far the largest JSON contract of
any `deep_reasoning=True` job in the codebase — 14 fields, several with
their own multi-clause instructions — versus 2-4 fields for every other
reasoning job (dispute, tradition, invention, laws, ...). It also can't
use a `json_schema` grammar (deliberately, since v1.3.37 — a grammar
would suppress the preceding `<think>` block), so its reasoning trace
and its unusually large free-form answer shared the exact same flat
`DEEP_REASONING_NUM_PREDICT_MULT` (1.5x) token budget every simple
2-field reasoning job also gets. On a real model, a genuine Nemotron 3
reasoning trace over this much required output can plausibly consume
the whole budget before any JSON is written; `_UNCLOSED_THINK_RE`
(client.py) then strips the entire dangling `<think>` block, leaving
nothing for `json.loads` — a `calls_errored` fallback with no visible
cause in the aggregate counters, exactly the blind spot item (2) below
fixes. New `PERSONAL_BELIEF_NUM_PREDICT_MULT=3.0` (`_schedule_llm_job`
gained a `num_predict_mult` override param) gives this one job real
extra headroom instead of raising the budget for every reasoning task;
the request-level timeout now scales proportionally with whatever
multiplier a job actually used (previously hardcoded to the flat 1.5x
regardless), so a job asking for more tokens also gets a fair chance to
generate them before the socket times it out.

**(2) Fallback diagnostics.** `CognitionRunner.run`/`_run_gated`
(llm/jobs.py) now return a 4th element, `diag` — a dict of
`fallback_reason`/`raw_model_output`/`parsed_json`/`validation_errors`,
populated on EVERY failure path (outer timeout, client socket timeout,
malformed JSON, unexpected exception), not just the aggregate counters
that already existed. The key fix making this possible: the client's
`capture["raw"]` dict was already being filled with the exact raw
completion text before any JSON-parse attempt (see `client.py`'s
docstrings) — but `_run_gated`'s exception handlers previously
discarded it entirely, returning bare `(fallback(), True, None)` with
the raw text silently lost. It's now read directly off the same local
`capture` dict every exception handler already has in scope, plus a
best-effort re-parse (`_diagnose_raw_output`, reusing `client.py`'s
`_extract_json_object`) so the dev console can show not just THAT a
call failed but WHAT the model actually said and WHY it didn't parse.
`_schedule_llm_job`'s `_runner` threads `diag` through to `_record_llm_
debug`, which folds it into `_last_llm_calls[name]` — already reachable
via `full_diagnostics()`'s existing raw-JSON dev-console dump, same
reachability precedent as `reflection_notebook`/`nature_pillar`, no new
endpoint needed. The daily-budget-exhaustion path (a separate, non-
`CognitionRunner` fallback route) gets its own synthetic `diag`
(`fallback_reason="daily_llm_budget_exhausted"`) for the same
visibility. `fallback_result` (the caller-side fallback dict, not
knowable inside `CognitionRunner`) is attached at each of the four
call sites in `simulation/engine.py`.

**(3) Single-adapter model-agnostic refactor.** New `llm.client.
LLMAdapter` (ABC): the entire contract between Hearthmind and any local
LLM backend — one `generate_json(...)` method plus a `build_from_
config(cls, config)` classmethod. `OllamaClient`/`LlamaCppClient` now
both inherit it; neither `llm/jobs.py`, `simulation/engine.py`, nor any
prompt/parse module under `llm/` imports either class by name or
branches on `config.llm_backend` — they only ever hold an `LLMAdapter`
reference and call `.generate_json(...)` on it (this was already
mostly true structurally via duck typing; the ABC + registry make it an
enforced, documented contract rather than an implicit convention). New
`llm.client.ADAPTER_REGISTRY: dict[str, type[LLMAdapter]]` is the
single dispatch point; `build_llm_client(config)` is now a two-line
registry lookup + `adapter_cls.build_from_config(config)` delegation
instead of a hand-rolled per-backend branch duplicating each adapter's
constructor fields. Adding a new backend is exactly: write a class
inheriting `LLMAdapter`, implement `generate_json`/`build_from_config`,
add one `ADAPTER_REGISTRY["name"] = MyAdapter` line — nothing else in
the codebase changes.

**(4) Nemotron 3 Nano 4B tuning.** `Config.llm_model` was already
`nemotron-3-nano-4b` (set v1.3.36) and `llm_backend` already
`"llamacpp"` (the default backend, v0.72.0) — this pass confirms
`LlamaCppClient` IS the Nemotron-tuned adapter (not a parallel unused
subclass — it already implements the "detailed thinking on/off"
system-prompt toggle plus the `reasoning_budget`/`enable_thinking`
request-level enforcement this model specifically needs, and lets
llama-server's own GGUF-embedded chat template handle role formatting
rather than hand-rolling one). New optional `top_p`/`min_p` fields
(`Config.llm_top_p`/`llm_min_p`, both `None`/unset by default) are
wired through but deliberately left unset: an attempt to consult the
model card at huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF for
its recommended sampling defaults was blocked by an outbound-fetch
failure in this environment (403 on every URL tried), so per CLAUDE.md's
"live user reports over unverified specs" discipline, no unconfirmed
number was invented — these two levers are ready for a future live-
tuning pass instead.

Verified: direct unit-style smoke tests of `CognitionRunner.run`
against a fake adapter for the malformed-JSON, LLM-disabled, and
success paths (confirming `diag` shape and raw-text recovery in each);
an engine-level test confirming `_schedule_llm_job`'s full budget-
exhausted fallback path writes the expected `fallback_reason` into
`_last_llm_calls`; `ADAPTER_REGISTRY`/`build_llm_client` construction
smoke test; `scripts/verify_native_soak.py` (2 seeds x 300 ticks)
byte-identical (no native module touched by this batch).

## [1.5.3] — B1/B2/B3 generalized to all five pillars

Explicit user directive, mid-turn correction on the B1/B2/B3 work below:
"you have only built nature pillar up until now, build all the other
pillars. Don't do half-jobs. Complete each and every checklist item
fully." The prior three versions proved the Pillar abstraction/
cognitive cycle/attention scheduler against Nature only, by design
(prove the shape once, generalize once proven) — this version is that
generalization.

New `cognition/pillar.py` factories: `default_village_pillar`/
`default_humans_pillar`/`default_innovation_pillar`/`default_
reflection_pillar`, each seeded with a real identity/self_model/
objectives for that pillar's actual domain. New `World.village_pillar`/
`humans_pillar`/`innovation_pillar`/`reflection_pillar`, fully wired
into `to_dict`/`from_dict`.

Rather than reimplement B2/B3's observe/interpret/backpressure/close
logic four more times, it was extracted from Nature's original inline
implementation into three shared `SimulationEngine` helpers —
`_pillar_observe_turn(pillar_name)`, `_pillar_interpret_backpressured
(pillar_name)`, `_pillar_close_cycle(pillar_name)` — and Nature's own
job was refactored to use them first (verified byte-identical
behavior), before wiring the four new pillars through the identical
helpers. Each pillar got exactly ONE representative existing job wired
through this shape (matching Nature's own precedent, not the larger
"refactor ~55 scattered jobs" ask, which stays explicitly out of
scope): Village → `_maybe_schedule_beliefs` (settlement-wide theory
formation), Humans → `_maybe_schedule_narrative_direction` (collective
mood/theme), Innovation → `_maybe_schedule_ontology_proposal` (new
concept origination), Reflection → `_maybe_schedule_reflection`
(cross-pillar hypothesis formation). Each job's prompt-builder
(`llm/beliefs.py`, `llm/narrative_direction.py`, `llm/ontology.py`,
`llm/reflection.py`) gained the same `emergence_observations` param
`nature_mind.build_prompt` already had. Confidence for a pillar's
mirrored `world_model` entry uses whatever real signal that job
already has (Village/Reflection: the job's own confidence field;
Innovation: 0.4, matching a freshly `"proposed"` concept's real
adoption-lifecycle starting value; Humans: the strongest real
`Settlement.mood` axis magnitude) — never a fabricated placeholder.

Dev-console surfacing: `full_diagnostics()` gained `village_pillar`/
`humans_pillar`/`innovation_pillar`/`reflection_pillar`, same raw-JSON-
only depth as the existing `nature_pillar` entry (nothing player-facing
reads any of the five yet).

Verified: direct smoke tests confirming all four new jobs' real observe
→interpret cycle-stage transitions and working_memory population; full
end-to-end apply()-completion tests (world_model entry creation,
working_memory clearing, cycle_stage reset to `observe`) for Humans and
Reflection specifically, awaiting the real async fallback resolution
path; a full `World.to_dict()`/`from_dict()` round trip covering all
five pillars simultaneously with each mutated; `scripts/verify_native_
soak.py` (2 seeds x 300 ticks) byte-identical.

## [1.5.2] — B3 "The Attention Scheduler," Nature first (roadmap Stage II, step 6)

Explicit user instruction: "Continue with roadmap" — Stage II step 6,
following step 5's cognitive cycle. B3 asks for "one budget arbiter
over all five [pillars]... priority from A22 salience + staleness +
player focus + inter-pillar messages," wired to the existing dynamic
pacing. Scoped like every step before it: round-robin over five
pillars is trivial with only Nature existing (it's always Nature's
turn); the real deliverable is the priority FORMULA itself, ready for
a genuine second pillar to arbitrate against.

New `hearthmind/cognition/attention.py`: `pillar_salience()` (the
strongest `magnitude` among A22 Emergence API entries tagged for a
pillar since its last turn — MAX not average, so one loud signal reads
as salient even amid a quiet stretch, `DEFAULT_SALIENCE=0.3` when
nothing tagged/magnituded exists), `compute_priority()` (weighted
combination — salience 0.5, staleness 0.3, inter-pillar messages 0.15,
player focus 0.05 — reflecting "maximize emergence per LLM call" over
mere time-since-last-turn), `backpressure_fraction()` (maps priority
0..1 to a 0.5..1.0 fraction of the shared backpressure limit a turn
tolerates before deferring — never a full bypass, same "scale the
threshold" shape `DIALOGUE_BACKPRESSURE_FRACTION` already uses
elsewhere, just computed instead of hardcoded).

`Pillar` gained `last_turn_tick` (the tick its cycle last genuinely
advanced — observe or interpret — feeding staleness), persisted.
`_maybe_schedule_nature_mind`'s `interpret` branch now computes a real
priority from the observations noticed since the pillar's last turn
(`world.emergence_log` filtered to `"nature"`) and staleness, then
defers under backpressure using that priority's scaled fraction
instead of the flat `_settlement_job_backpressured()` gate every other
settlement job shares — a quiet, fresh turn defers earlier under
pressure; a salient or long-overdue one tolerates more backlog first.
"Wired to the existing dynamic pacing" is otherwise already true
globally (the tick-loop's LLM-pressure-aware slowdown predates this
work and isn't pillar-scoped) — nothing here duplicates or replaces
it.

Deliberately not attempted: `message_count`/`player_focus` are both
real, ready inputs that read 0 for every pillar today — no second
pillar exists to message from (B4), and nothing connects player
attention to a specific pillar yet. Both terms activate automatically
once those exist, no further wiring needed here.

Verified: direct smoke tests (`pillar_salience`'s max-not-average
behavior, pillar-filtering, and window-boundary handling;
`compute_priority`'s bounds at 0 and 1; `backpressure_fraction`'s
floor/ceiling), an engine-level test confirming a real `_maybe_
schedule_nature_mind` observe turn sets `last_turn_tick` and that a
baseline-priority computation yields a real sub-1.0 tolerance fraction,
plus a `to_dict`/`from_dict` round-trip for the new field.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## [1.5.1] — B2 "The continuous cognitive cycle," Nature first (roadmap Stage II, step 5)

Explicit user instruction: "Continue with roadmap" — Stage II step 5,
following step 4's Pillar abstraction (v1.5.0). B2 asks for each
pillar to run a genuine observe→interpret→remember→plan→act→reflect
cycle, resumed across turns rather than a single timer-fired job.

`cognition/pillar.py`'s `Pillar` gained `cycle_stage`/`CYCLE_STAGES`
(the full six-stage vocabulary, reserved for future generality),
`working_memory` (bounded `WORKING_MEMORY_MAX=5` scratch space, distinct
from the long-lived `memory` list), `note_observation()`, `clear_
working_memory()`, `set_cycle_stage()` — all persisted.

`_maybe_schedule_nature_mind` now branches on `nature_pillar.
cycle_stage` instead of firing the same monolithic call every season:
an `observe` season reads `World.emergence_log_recent()` (A22) filtered
to entries tagged `"nature"`, writes their summaries into `working_
memory` (zero LLM cost), and advances to `interpret` — a real C1
"perception channel" wiring (Nature now genuinely reads the curated
Emergence API, not just raw event categories; nothing read `emergence_
log` before this). The FOLLOWING season is the `interpret` turn: the
existing LLM call fires exactly as before, now also grounded in the
observations gathered last turn (`llm/nature_mind.py`'s `build_prompt`
gained an optional `emergence_observations` param, rendered as "What
you noticed since last time:" when non-empty) — remember/plan/act/
reflect still happen synchronously inside one call (`apply()`), which
then clears `working_memory` and returns `cycle_stage` to `observe`,
closing the cycle. A no-op revision (the model finds nothing worth
changing) also closes the cycle rather than leaving it stuck retrying
`interpret` forever.

Real consequence, not free: `nature_mind`'s LLM call volume is now
halved (one real call every OTHER season instead of every season) —
a genuine trade of raw call frequency for a resumable, perception-
grounded cycle, consistent with "maximize emergence per LLM call."
If a critical call is ever deferred (budget/failure), `cycle_stage`
stays on `interpret` and the next season retries from there — nothing
is lost, matching the standing critical-cognition deferral discipline
(CLAUDE.md's tick-loop workflow rule).

Deliberately NOT attempted: bounded bookkeeping for the four
intermediate stage names (`remember`/`plan`/`act`/`reflect`) as
separate persisted stops — Nature's one LLM call still performs all
four synchronously, matching the project's "one call does everything"
convention; splitting them across turns is future work if a pillar
ever needs it. B3 (attention scheduler) and generalizing this cycle
beyond Nature remain open Stage II steps.

Verified: direct smoke tests (`Pillar` cycle-stage/working-memory
semantics + round-trip, `nature_mind.build_prompt`'s new param), an
engine-level test calling the real `_maybe_schedule_nature_mind`
directly and confirming the observe→interpret stage transition and
working-memory population from a seeded `emergence_log` entry.
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical.

## [1.5.0] — B1 "The Pillar abstraction," Nature first (roadmap Stage II, step 4)

Explicit user request: "Start stage 2" — the first step of the
roadmap's Stage II (docs/MASTERCHECKLIST-2026-07-22.md), the "five
minds" refactor. B1 is the doc's own "keystone": each future pillar
(Humans, Village, Nature, Innovation, Reflection) is meant to be a
persistent conscious entity with identity, self-model, world-model,
living memory, objectives, and inbox/outbox — this pass proves that
shape against ONE pillar (Nature) before replicating it four more
times, per the roadmap's explicit sequencing.

New `hearthmind/cognition/pillar.py`: `Pillar` (self_model — an open
dict of what the pillar is/wants; `world_model` — a list of typed,
revisable theories via `make_world_model_entry`, explicitly tagging
`status: "observation"|"hypothesis"` per B9's "distinguish observation
from hypothesis" line; `memory` — a capped consolidated-knowledge list,
`MEMORY_MAX=40`, the simplest possible stand-in for B8's real
consolidate/forget/reinforce cycle; `objectives`; `inbox`/`outbox` —
B4's typed `MESSAGE_KINDS` vocabulary, structurally present but unused
until a second pillar exists to message). Plain-dict-backed
(`to_dict`/`from_dict`), same persistence convention as every other
World-scoped store.

New `World.nature_pillar` (seeded via `default_nature_pillar()` —
genesis-time identity/self-model/objectives, not LLM-authored: what a
pillar fundamentally is isn't itself a revisable belief).
`_maybe_schedule_nature_mind`'s existing apply() (unchanged mechanics)
now mirrors every belief formation/revision into `nature_pillar.
world_model` (tracked via a new `pillar_entry_id` key on each
`World.nature_beliefs` entry, so a later revision updates the same
pillar entry) and appends a `remember()` note — `World.nature_beliefs`
itself is completely untouched, so every existing reader (town_brain
grounding, the ontology bridge, `/diagnostics`) keeps working exactly
as before. This is additive proof the shape holds against a genuine
production call site, not a standalone demo structure nobody writes
to.

Deliberately NOT attempted this pass: the checklist's larger B1 ask
("refactor the ~55 scattered jobs into acts of five pillars") — that's
B2 (the continuous observe→interpret→remember→plan→act→reflect cycle)
and the rest of Stage II; inter-pillar messaging (B4) stays inert since
Nature is the only pillar that exists yet; B8's real memory-
consolidation cycle stays a capped FIFO list, not genuine
consolidate/forget/reinforce/reinterpret.

UI: `full_diagnostics()["nature_pillar"]` — same dev-console-only
reachability as `reflection_notebook`/`emergence_log` (nothing
player-facing reads a pillar's self-model/world-model yet; the shape
is being proven, not shown off).

Verified: direct smoke tests (`Pillar`'s upsert-or-append world-model
semantics, memory cap, `to_dict`/`from_dict` round-trip, `make_
world_model_entry`/`make_message` validation), an engine-level test
exercising the actual `nature_mind` apply() mirroring logic (new
belief, revision, round-trip through `World.from_dict`, `full_
diagnostics()` reachability). `scripts/verify_native_soak.py` (2 seeds
x 800 ticks) byte-identical — the mirrored write only runs inside a
critical LLM job's `apply()`, which never fires in an LLM-disabled
soak, so this is a pure regression check on everything else.

## [1.4.9] — A1 FieldGrid + A16 Graph algorithms (roadmap Stage I, steps 2-3 — Stage I complete)

Explicit user request: "complete stage 1" — the remaining two steps of
the roadmap's Stage I (docs/MASTERCHECKLIST-2026-07-22.md), after
v1.4.8 shipped step 1 (the Emergence API). Both scoped to a real,
minimal proof-of-shape rather than the doc's full wishlist, matching
the same discipline v1.4.8 used.

**A1 FieldGrid** (step 2): new `hearthmind/world/fields.py` —
`FieldGrid`, a dict of named `FIELD_GRID_SIZE`x`FIELD_GRID_SIZE` (3x3,
matching `WEATHER_REGION_GRID`) dense scalar grids, deliberately coarse
per the roadmap's own scoping note ("the interface matters more than
resolution day one"). `World.fields`, stepped once per tick right
after `population.tick` (agent positions must be current). Ships one
concrete field, `population_density` (agents per region, normalized),
as a real per-tick-computed consumer proof rather than bare
infrastructure: `_choose_fission_site` now prefers a region the field
doesn't read as crowded (`POPULATION_DENSITY_FISSION_AVOID_THRESHOLD
=0.75`) when an alternative exists — never a hard block. The other
eleven named fields det_sys.md lists (moisture, fertility, disease-
pressure, ...) are explicitly not built this pass; each is an additive
follow-up onto the same grid. R7 deviation flagged (Python, not C++)
— same precedent as spatial weather/mining scars/minerals: a 3x3 grid
is under 200 floats total, several orders below where a native port
would pay for itself.

**A16 Graph algorithms** (step 3): new `hearthmind/world/graph_
algorithms.py` — `build_relationship_graph`/`degree_centrality`/`most_
central_agent`, a real graph-theoretic algorithm (weighted-degree
centrality, negative edges clamped to 0 since this measures
connectedness not fondness) run over the existing pairwise relationship
ledger rather than a second graph structure. New `Settlement.social_
hub_agent_id` + `SimulationEngine._detect_social_hub` (season cadence,
every settlement — cheap enough not to need round-robin gating, zero
LLM cost) recomputes each settlement's most-central living agent and
emits an A22 `unexplained_shift` observation only when the hub actually
changes (edge-triggered, same discipline as `_detect_settlement_
bottlenecks`). Community detection — the doc's other headline example
— was already shipped as `InstitutionKind.FACTION` detection (v0.80.0)
under a different name; not duplicated. Betweenness/network-flow/tech-
dependency-DAG metrics remain flagged future follow-ups.

UI: `social_hub_agent_id` reaches `Settlement.summary()`; a new
"Social hub" stat-tile row (main UI, per the Observatory direction's
"plain-language facts" precedent — this is a structural fact about a
real named person, not under Phase G's ambiguity discipline) resolves
the id to a name via the existing live agent broadcast. `world.fields`
and the graph algorithms module stay dev-console-invisible for now
(no diagnostics field added) — nothing yet needs to inspect the raw
grid; `population_density`'s only visible effect is fission-site
behavior, same as any other deterministic mechanic.

This closes roadmap Stage I ("Senses & substrate") — all three steps
shipped (v1.4.8-v1.4.9). Stage II (the five-pillar refactor) is the
first real consumer of `emergence_log`/`fields`/graph algorithms
together; work from it only on future explicit direction.

Verified: direct smoke tests (`FieldGrid` region bucketing/step/round-
trip, `graph_algorithms` centrality/tie-breaking/isolated-node
handling, `_detect_social_hub`'s edge-triggering + round-trip
persistence, a real engine tick confirming `population_density`
populates). `scripts/verify_native_soak.py` (2 seeds x 800 ticks, plus
a longer single-seed run crossing a real season boundary to exercise
`_detect_social_hub` in the live tick loop) — byte-identical.

## [1.4.8] — A22 "The Emergence API" (roadmap Stage I, step 1)

Explicit user request: "Start step 1: the Emergence API" — the first
concrete implementation step off v1.4.7's roadmap
(docs/MASTERCHECKLIST-2026-07-22.md). A22 asks for a per-subsystem
structured observation stream from the deterministic Body — anomalies,
novel combinations, bottlenecks, unexplained shifts, opportunities —
tagged by which future cognitive pillar (humans/village/nature/
innovation/reflection) would care, ahead of any pillar actually
consuming it ("build the sense organ before the mind that uses it,"
same sequencing `Population.voice_conversation` had before the voice-
pair feature read it).

New `hearthmind/world/emergence.py`: `OBSERVATION_KINDS`/`PILLARS`
closed vocabularies and `make_observation()`, a plain-dict factory
(same convention as `highlights`/`reflection_notebook` — no per-type
(de)serialization to maintain) that validates both vocabularies at
construction (`ValueError` on a bad call site, since this is an
internal producer contract, not user input). New `World.emergence_log`
(capped `EMERGENCE_LOG_MAX_STORED=500` — a busier future stream than
`highlights`' 30, but still small dicts) + `World.next_emergence_id`,
wired into `to_dict`/`from_dict`; `World.emergence_log_recent()`
mirrors `knowledge_tree()`/`causal_threads_list()`'s newest-first
on-demand shape.

Deliberately reused already-computed, already-edge-triggered signals
rather than building a new scanning system: `SimulationEngine.
_append_highlight` now mirrors into `_append_emergence` for every
highlight kind with an entry in the new `_HIGHLIGHT_EMERGENCE_MAP`
(first_invention, era_advance, first_ritual, first_religion,
family_feud, successor_founded, extinction_near_miss,
population_anomaly — every existing highlight kind, each given a
kind/subsystem/pillar-tuple mapping); the reflection hypothesis
lifecycle (`_maybe_schedule_reflection`'s `apply` closure on formation,
`_append_reflection_conclusion` on confirm/refute) each emit one
observation; `_maybe_spread_concepts` emits `novel_combination` the
first tick an `InventedConcept`'s status transitions to `established`.
One genuinely new detector: `_detect_settlement_bottlenecks` (riding
`_log_daily_metrics`'s existing once-per-sim-day cadence, no new
polling loop) emits `bottleneck` the first day a settlement's
materials drop below `cheapest_founding_cost()` — the same bar
`cognition.py`'s per-agent `materials_critical` flag already uses, but
settlement-scoped and edge-triggered (`_materials_critical_flagged`,
a plain runtime set, never persisted) so it fires once on the crossing
and again only after a real recovery, not every day the settlement
stays poor.

`GET /emergence` (interface/app.py) + `WorldBroadcaster.
set_emergence_log_provider`/`get_emergence_log` (interface/api.py, same
on-demand-provider shape as knowledge-tree/causal-threads — up to 500
entries is too large for the per-tick WS payload, and nothing needs
sub-second freshness). UI surfacing: `full_diagnostics()` gained
`emergence_log_total`/`emergence_log_by_kind`/`emergence_log_recent`
(last 10, kind/subsystem/summary/pillars only) — the dev console's
existing "Full diagnostic report" button already dumps this raw, the
same reachability `reflection_notebook` has always had with no
dedicated panel; a stream with no consumer yet doesn't warrant a new
main-UI surface ahead of Stage II's pillar refactor actually reading
it.

No pillar reads `emergence_log` yet — that's Stage II of the roadmap.
Verified: direct smoke tests (`make_observation` kind/pillar
validation + magnitude clamping; `_append_highlight`→`_append_emergence`
mirroring including a non-mapped highlight kind correctly emitting
nothing extra; the 500-entry cap; `emergence_log_recent`'s newest-first
ordering; `to_dict`/`from_dict` round-trip; the bottleneck detector's
edge-triggering — fires once on crossing, silent while still critical,
clears on recovery without emitting again). `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical — no native module
touched, but `_append_emergence`/`_detect_settlement_bottlenecks` run
inside/adjacent to the tick loop.

## [1.4.7] — File the Master Checklist (Body/Mind/Seam audit) + a 30-step implementation roadmap

Explicit user request: add an uploaded consolidated audit doc,
"Hearthmind — The Complete Master Checklist," to the project docs, and
produce a concrete implementation roadmap (sequence + step count) for
it. Docs-only — no code changed.

The checklist covers three parts against v1.4.1: **Part A**, the
deterministic "Body" (25 systems from an external `det_sys.md` — fields,
CA/diffusion, procgen-as-runtime, affordances, materials, chemistry,
genetics, graphs, information ecosystems, the Emergence API, etc.);
**Part B**, the cognitive "Mind" (9 items from an external `LLM_
Pillars.md` — five persistent pillars: Humans/Village/Nature/
Innovation/Reflection, each with identity/self-model/world-model/
memory/attention); **Part C**, the "Seam" (5 items — how Mind perceives
and reshapes Body without violating it). Headline finding: most of
today's Body systems are generated-once-at-creation and static/random-
walk thereafter (rivers carved once, a 9-region climate grid not
per-tile fields, no material/affordance/genetics/chemistry model) —
det_sys.md's "procedural generation as continuous runtime, not a
world-gen step" is the through-line gap across nearly every PARTIAL
item.

Filed verbatim as `docs/MASTERCHECKLIST-2026-07-22.md`, same convention
as every other externally-submitted vision/audit doc this project
keeps (docs/IDEAS-2026-07-EMERGENCE.md, docs/VISION-2026-07-21-
SELFEVOLVING.md, docs/VISION-2026-07-22-LIVINGTERRARIUM.md, docs/
DEFINITIVECHECKLIST-2026-07-21.md). New "Implementation roadmap"
section appended to the same file: the doc's own 4-phase thematic
SEQUENCE (senses/substrate → five minds → interaction → deepen the
Body) is broken into **30 concrete, independently-shippable steps** —
Stage I (senses & substrate, 3 steps: Emergence API, FieldGrid, graph
algorithms) → Stage II (the five minds, 6 steps, Nature first) → Stage
III (player-facing + interaction, 5 steps) → Stage IV (deepen the
Body, 16 steps, ordered by leverage — hydrology first, temporal-
compression pipeline last). 5 of the checklist's 39 items (A9/A23/A24/
A25/C4) are standing review-time discipline folded into every step
rather than separate line items, hence 39 checklist items → 30 build
steps. One design decision flagged as blocking only Stage III's step
14 (Humans collective vs. individual-NPC disagreement in dialogue),
not any earlier step. A short CLAUDE.md pointer entry added alongside
the doc's other vision-doc pointers, same "work from it only on future
explicit direction naming a specific step" standing rule as every
other filed vision doc — this pass is planning/filing only, nothing
implemented.

## [1.4.6] — Widen voice_conversation's retention cap so the repetition backstop actually reaches

Explicit user follow-up on v1.4.5, off a fresh `/diagnostics` +
dialogue log: self-naming is fixed (confirmed absent across the whole
log) and `calls_errored`/`calls_timed_out` both stayed low/zero — but
exact-line repeats were still visible ("Wilhelmina: 'Is that so.'"
recurring, "then we'll dream it real, don't we?" recurring), even
though v1.4.5's dedup backstop is running.

Root cause: `dialogue._is_near_duplicate_line` only ever checks
against what's still IN `Population.voice_conversation`'s ring, capped
at `MAX_VOICE_CONVERSATION_STORED=24`. The reported repeats recurred
~650 ticks apart — at the voice pair's fastest cadence (`VOICE_
DIALOGUE_COOLDOWN_TICKS=5`) that's 100+ exchanges, meaning the earlier
occurrence had long since been evicted from a 24-entry ring by the
time the repeat happened; the backstop was working exactly as coded,
its lookback window was just too short to ever catch a repeat that far
apart. Fixed by raising `MAX_VOICE_CONVERSATION_STORED` 24 -> 220 —
comfortably covers 1000+ ticks of continuous fastest-cadence exchanges
before evicting anything, at negligible memory cost (small dicts, a
capped list, no LLM cost either way since the PROMPT itself still only
ever reads the newest `VOICE_CONVERSATION_HISTORY_TURNS` (6) — only
the backstop's own lookback widens).

Verified: `MAX_VOICE_CONVERSATION_STORED` constant check,
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
— no native module touched, and this constant only governs how much
of an already-deterministic Python list gets retained.

## [1.4.5] — Fix voice-pair repetition attractor and self-name addressing

Explicit user follow-up after v1.4.4 made the voice pair's dialogue
visible in the UI for the first time: reading the actual conversation
history showed two real quality bugs — the pair converges onto a
handful of images/complaints and recites them near-verbatim many
exchanges apart ("Ash still smells like home, Osric." repeated
verbatim 5+ times across a ~500-tick span; "Cold bread? I'm already
cold from the wind." similarly), and a speaker sometimes addresses
THEMSELF by name mid-line (Osric saying "...Osric" about himself,
Liora saying "...Liora" about herself) rather than only ever naming
the other person.

**Repetition.** No novelty/dedup check existed for voice-pair lines at
all — `_run_dialogue`'s `is_spreading_tic` (tail-fingerprint check
across DIFFERENT speakers) was never wired into `_run_voice_dialogue`,
and there was nothing checking a speaker's line against their OWN
prior lines either way. Root cause: the voice pair's frequent cadence
(`VOICE_DIALOGUE_COOLDOWN_TICKS=5`) plus a small model repeatedly
handed similar internal-state/town-digest input converges onto the
same few images rather than writing something new each time — the
exact "small model re-condenses the same idea when shown similar
context" shape `FOLKLORE_DUPLICATE_OVERLAP` already fixed for monthly
tale-telling (v1.3.2), just for this much higher-frequency job. Two-
part fix, same "prompt hint + deterministic backstop" pattern as that
earlier fix: `VOICE_SYSTEM_PROMPT` now explicitly tells the model not
to repeat an image/complaint it's already used; new `dialogue.
_is_near_duplicate_line`/`VOICE_LINE_DUPLICATE_OVERLAP=0.6` (Jaccard
word overlap, stdlib only) is the deterministic backstop for when a
weak model doesn't comply — checked per speaker against the FULL
stored `Population.voice_conversation` ring (up to `MAX_VOICE_
CONVERSATION_STORED=24` lines), not just the ~6 turns fed into the
prompt itself, since the live-reported repeats recurred well outside
that shorter prompt window. A near-duplicate degrades only THAT one
side to the deterministic fallback pool — the other speaker's
(presumably still-novel) line is kept, rather than discarding the
whole exchange the way `_is_sane_line` failures already do.

**Self-naming.** `VOICE_SYSTEM_PROMPT` now explicitly says a speaker
may name the OTHER person but must never say their own name — a real
person doesn't call themself by name mid-sentence. New `dialogue.
_strip_self_address(line, own_name)` is the deterministic backstop:
strips a clear vocative use of the speaker's own name (immediately
after/before a comma — "...we were, Osric." or "Osric, I still...")
while leaving the OTHER speaker's name and any non-vocative substring
occurrence untouched. `parse_voice_dialogue` gained optional
`speaker_a_name`/`speaker_b_name`/`recent_lines_a`/`recent_lines_b`
params (backward compatible — all default to empty/`None`, a no-op)
wired at the one call site, `SimulationEngine._run_voice_dialogue`.

Verified: direct unit tests (trailing/leading self-vocative stripping,
the other speaker's name staying untouched, near-duplicate detection
on both an exact repeat and a light paraphrase while sparing a genuine
novel line, and an end-to-end `parse_voice_dialogue` check confirming
a repeated line degrades to fallback on only its own side while the
novel side survives). `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical — no native module or persisted field touched.

## [1.4.4] — Fix timeout misclassification/truncation on reasoning calls; visible voice-pair dialogue; deep-reasoning diagnostics

Explicit user follow-up on v1.4.3, with a fresh review pack + `/diagnostics`
attached: reasoning calls were still failing, no voice-pair dialogue was
visible anywhere in the UI, and some completions looked truncated
mid-sentence. Four real bugs found and fixed, none of them the same
bug as v1.4.3's fix (which genuinely worked — `calls_errored` in the
new diagnostic was 2/313, not the near-100% of before).

**Timeout misclassification (the "is timeout playing a role" question).**
`LlamaCppClient`/`OllamaClient.generate_json` open the HTTP request
with `urlopen(request, timeout=self.timeout_seconds)`; `jobs.py`'s
`CognitionRunner._run_gated` separately wraps the whole call in
`asyncio.wait_for(..., timeout=self.client.timeout_seconds + 5.0)` as
"defense in depth." Since the inner socket timeout is strictly smaller
than the outer one, the inner timeout ALWAYS fires first — and it
raised plain `LLMUnavailable`, landing in `calls_errored`, not
`calls_timed_out`. The `calls_timed_out` counter has read 0 in every
diagnostic this project has ever produced; it was structurally
incapable of ever incrementing. New `client.LLMTimeout(LLMUnavailable)`
raised specifically on a socket-level timeout (`TimeoutError`, or a
`URLError` whose `.reason` is one); `jobs.py` now catches it before the
generic `LLMUnavailable` and counts it correctly.

**Reasoning calls genuinely needed a longer timeout.** The new
diagnostic's `personal_belief` (a `deep_reasoning=True` task) showed
p95 latency 146.7s against an un-scaled 125s timeout (120s config + 5s
grace) — the socket timeout was cutting off calls that were still
legitimately generating a `<think>` trace plus an answer, not stuck.
New `DEEP_REASONING_TIMEOUT_MULT=1.5` (`simulation/engine.py`, mirrors
`DEEP_REASONING_NUM_PREDICT_MULT`'s own ratio) scales the timeout in
step with the already-scaled token budget whenever `reasoning=True`;
both clients' `generate_json` and `CognitionRunner.run`/`_run_gated`
gained a `timeout_override` param threaded end to end.

**Truncation.** A `json_schema`'s `maxLength` is enforced by the
sampler at the character level — the grammar force-closes the JSON
string (and the object around it) the instant the cap is hit, with no
chance for the model to finish its sentence. Both diagnostics showed
this exact shape (`mind.voice` ending "...a whisper that remains, a
rhythm," `chronicle.summary` ending "...ends not with fanfare but
with"), both landing within a couple characters of that field's
`maxLength`. New `client._trim_truncated_string`/`_trim_truncated_
strings`: only touches a string field whose length is at/near its
schema's declared cap, trimming back to the last complete sentence (or
the last complete word before a dangling comma fragment if no sentence
exists) — applied to every schema-constrained call's parsed result in
both clients.

**"No dialogue at all" — a real UI bug, not a backend gap.** The
attached diagnostic's own `event_category_counts` showed `dialogue:
137` and `voice_dialogue` (the LLM task) calls succeeding fine — the
voice pair WAS talking. The bug: since v1.4.0's redesign, `is_llm` in
`_apply_pending_dialogue_results` can only ever be the one dedicated
voice pair (every other pair resolves through the always-`is_llm=False`
deterministic path), but the category logic still gated visibility on
`surfaced` (a rumor/relationship-threshold flag) — an ordinary
voice-pair line that didn't cross that threshold logged under the
plain `dialogue` category, which is `skip: true` in `app.js` (a
holdover from when many core-cast pairs produced real LLM chatter and
most of it needed hiding). The pair's actual conversation — the whole
point of the feature — was invisible in the main event feed unless a
line happened to also cross the surfaced threshold. Fixed: an ordinary
voice-pair line now logs under a new, visible `voice_dialogue`
category (💬); `dialogue_surfaced` (💬✨) still marks the stronger case.
`app.js`'s thought-flash map marker (a brief pulse over a core-cast
agent on a genuine LLM exchange) updated to match.

**Deep-reasoning diagnostics, per explicit request.** `CognitionRunner`
gained `reasoning_calls_attempted/succeeded/timed_out/errored` plus a
reasoning-only latency percentile window, surfaced as a new `reasoning`
sub-object in `llm_stats` (`/diagnostics`); `_last_llm_calls` and
`llm_prompt_stats` entries now carry a `reasoning: bool` tag so a
reasoning-specific failure is traceable per-task, not just in the
aggregate.

Verified: direct unit tests for `LLMTimeout` classification (socket
timeout vs. connection-refused vs. generic failure), `timeout_override`
reaching the request, `_trim_truncated_string`/`_trim_truncated_
strings` (sentence-boundary trim, dangling-fragment trim, only-near-cap
gating), the voice-pair dialogue category fix (an `is_llm=True` queued
result now logs `voice_dialogue`/`dialogue_surfaced`, never the hidden
`dialogue`), and the reasoning load-shed/timeout-scaling interaction
end to end through `_schedule_llm_job`. `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical — no native module or persisted
field touched.

## [1.4.3] — Fix reasoning-mode calls erroring out; dynamic/load-aware reasoning toggle

Explicit user follow-up on v1.4.2: a fresh review pack + `/diagnostics`
showed calls STILL erroring after that fix — this time `calls_errored`
5/5 (100%) on the `mind` task specifically, a task that has never been
`deep_reasoning=True`. Avg latency for those calls was ~114s against a
measured ~11.24 tok/s decode rate — roughly 1280 tokens generated
against a 512-token `max_tokens` request, i.e. the model was still
generating well past its budget with no JSON ever produced.

Root cause: `scripts/run.sh`'s `LLAMA_REASONING=auto` (the v1.3.37
default) leaves the server's reasoning budget open for every call: the
app's own per-call "detailed thinking off" system-prompt phrase is
only a soft hint, and this model does not reliably honor it — it kept
generating an (unclosed, budget-exhausted) `<think>` trace even for
routine, non-`deep_reasoning` tasks, so `content` never contained an
answer at all. `_THINK_BLOCK_RE` only ever matched a *closed*
`<think>...</think>` pair, so a truncated trace reached `json.loads`
whole and failed every time. Both LLM clients (`hearthmind/llm/
client.py`) now assert `reasoning=False` at the REQUEST level, not
just the prompt level — `LlamaCppClient` sends `reasoning_budget: 0` +
`chat_template_kwargs: {"enable_thinking": false}` (llama-server's
per-request equivalent of the already-proven `--reasoning-budget 0`
CLI flag; both fields are additive/ignored if the server build doesn't
recognize them) whenever `reasoning=False`, which is sampler-enforced
rather than merely requested — this is the actual fix. New `_UNCLOSED_
THINK_RE` strips a dangling, never-closed `<think>` block (applied
only when `_THINK_BLOCK_RE` finds no closed pair) as defense-in-depth
for any server/model combination where the per-request override is a
no-op — the completion still fails cleanly as `LLMUnavailable`/
fallback (there genuinely is no answer in a truncated trace), just
without dumping a multi-hundred-token half-finished reasoning trace
into the error message.

Second, explicit user directive: reasoning is expensive (several times
a routine call's latency) and should be reserved for genuinely crucial
tasks, dynamically shed under load rather than either a global on/off.
New `REASONING_LOAD_SHED_RATIO=0.9` (`simulation/engine.py`) —
`_schedule_llm_job`'s `reasoning` computation now also requires `llm_
pressure_ratio() < REASONING_LOAD_SHED_RATIO`; a `deep_reasoning=True`
job whose queue is already backing up runs WITHOUT a trace that one
call (same fast path as every routine task) instead of deferring or
dropping — the decision still gets made, just without the extra cost,
shedding load at exactly its most expensive point, before `LLM_
PRESSURE_SLOWDOWN_START_RATIO` (0.75) pacing or `LLM_PRESSURE_PAUSE_
RATIO` (2.0) even engage. `scripts/run.sh`'s `LLAMA_REASONING` doc
comment rewritten to describe both the server-wide ceiling and the new
per-request/per-load override together, since a reader tuning one
without knowing about the other would draw the wrong conclusion about
what each lever actually controls.

Verified: direct unit tests (`reasoning=False` sends the request-level
override, `reasoning=True` omits it and keeps the server default;
closed vs. unclosed `<think>` blocks parse correctly on both clients;
`_schedule_llm_job` keeps `reasoning=True` under low `llm_pressure_
ratio()` and drops to `False` under high pressure even with `deep_
reasoning=True`, and a routine non-`deep_reasoning` job never gets
`reasoning=True` regardless of pressure), `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical — no native module or
persisted field touched.

## [1.4.2] — Fix voice_dialogue's missing JSON schema; harden JSON extraction against wrapped completions

Live-diagnostic-driven fix: a pasted `/diagnostics` snapshot showed
`llm_stats.calls_errored` at 50% (6 of 12 attempted) on the voice
pair's own call (now the highest-volume task after v1.4.1's cooldown
drop to 5 ticks), plus one successful "mind" call whose `voice` field
came back containing visible leaked reasoning text ("speaks in short,
plain sentences 12 words? Actually voice field is ").

Root cause of the error spike: `_run_voice_dialogue` was the one
dialogue-shaped LLM call site never given a `json_schema` — every
other schema-eligible task (`cognition`, `dialogue`, `mind`, ...) went
through FT.0's grammar-constrained decoding (structurally guaranteed
valid JSON at the sampler level), but `voice_dialogue` didn't exist
yet when that schema set was built and was left unconstrained,
free-generating on a model that (per the "mind" evidence) doesn't
reliably keep meta-commentary out of its answer even when explicitly
told "detailed thinking off." New `"voice_dialogue"` entry in
`llm/json_schemas.py` (line_a/line_b/sentiment/topic, mirroring
`"dialogue"`'s shape at the wider `VOICE_MAX_LINE_CHARS`), wired into
`_run_voice_dialogue`'s `_cognition_runner.run(json_schema=schema_for_
task("voice_dialogue"))` call.

Defense in depth for every remaining unconstrained task (`beliefs`/
`personal_belief`, and anything future): `llm/client.py`'s new
`_extract_json_object()` — when a raw completion isn't itself valid
JSON, retries with the substring from the first `{` to the last `}`
before giving up. Recovers a completion wrapped in stray prose
("Sure, here's the JSON: {...}") or a markdown code fence that a
grammar-less small model occasionally emits despite the system
prompt's explicit instruction not to — a no-op for the already-common
case of a bare JSON response. Wired into both `OllamaClient` and
`LlamaCppClient`'s final parse step, tried only after the plain
`json.loads` has already failed once.

The garbled-but-schema-valid "mind" content itself (a call that
technically succeeded, `additionalProperties: False` + grammar
correctly enforced the shape) is a separate, harder problem — the
model producing low-quality-but-structurally-valid string content —
not something a schema or JSON-extraction fix can address; flagged as
a live model-quality observation, not a bug fixed here.

Verified: direct test of `_extract_json_object` against bare/prefixed/
code-fenced/unparseable inputs, `scripts/verify_native_soak.py` (2
seeds × 800 ticks) byte-identical (no native module touched, but the
LLM-call path runs on every schedule regardless of LLM enablement).

## [1.4.1] — Shifting protagonists: narrative-significance-driven voice pair rotation

Explicit user follow-up on v1.4.0's voice pair: trigger far more often
("every 5 ticks or something like that"), and rotate WHO the pair is
roughly weekly, driven by narrative significance rather than fixed
prominence — "some weeks the mayor dominates, other weeks it's a
grieving parent, later an inventor, a rebel, or a council elder... a
simulation with shifting protagonists rather than permanent stars."

**Cadence**: `VOICE_DIALOGUE_COOLDOWN_TICKS` 60 -> 5.

**Narrative-significance scoring**: new `Population._narrative_
significance(agent, extra_scores)` — a `_prominence` baseline (so an
otherwise-quiet week still favors an established figure) layered with
real event bonuses: `NARRATIVE_GRIEF_BONUS` (dominant emotion is
grief — "a grieving parent"), `NARRATIVE_EMOTION_BONUS` (any other
dominant emotion), `NARRATIVE_REBEL_BONUS` (an active hardened feud in
`Agent.relationship_flags` — "a rebel"), and `NARRATIVE_EXTREME_EVENT_
WEIGHT` × `Agent.extreme_event_count` (Phase 3.B's disaster-survival/
feud/widowhood tracker — a life visibly marked by extreme events).
`extra_scores` (an `{agent_id: bonus}` dict) carries the two signals
that live outside `Population` — a recent invention (`World.invented_
concepts`, `VOICE_NARRATIVE_INVENTOR_BONUS`, ~a season's recency
window) and active COUNCIL membership (`VOICE_NARRATIVE_COUNCIL_
BONUS`, "a council elder") — both computed by the new `SimulationEngine.
_voice_narrative_extra_scores()` since `Population` deliberately
doesn't reference `World`/`Settlement`.

**Selection**: `select_voice_pair` now picks this week's "protagonist"
(highest narrative significance) then partners them with their
strongest bond among the remaining core cast (falling back to the
next-highest-significance candidate if they have no such bond) —
reusing a new shared `_strongest_core_bond` helper also used by the
existing death-triggered rotation.

**Weekly rotation**: `maintain_voice_pair` gained `week_rotation: bool`
— the engine passes `"week_end" in events` (the calendar boundary
`SimClock` already computes) alongside `extra_scores`, forcing a fresh
`select_voice_pair` reselection even when the current pair is still
alive. No forced "never repeat" rule: if the same pair genuinely
remains the town's liveliest story, they stay — a no-op reselect isn't
treated as a change (no spurious `voice_pair_change` event/thread
reset). Death-triggered rotation (survivor's strongest bond, fresh
pair if both die) is unchanged.

Verified: direct smoke test (baseline prominence tie -> grief bonus
promotes the grieving agent -> partnering picks their strongest bond
-> week_rotation reselecting the same winner is a no-op -> an
inventor's extra score wins the next week's rotation),
`scripts/verify_native_soak.py` (2 seeds × 800 ticks) byte-identical.

## [1.4.0] — The voice pair: LLM dialogue narrowed to one deep, continuing conversation

Explicit user directive: disable LLM dialogue for every NPC pair except
exactly ONE fixed core-cast pair, and spend the freed-up budget making
that one pair's conversation genuinely deep — longer lines, real
continuity across calls (each reply picks up from what was just said,
not a fresh small-talk opener), grounded in a concise town summary and
each speaker's own internal state. Rotates to a new pair on death. All
other dialogue (the vast majority) stays deterministic-only, same as
it's always been for non-core pairs — unchanged mechanically, just no
longer LLM-eligible even for a core-core pairing that isn't the voice
pair.

**`Population.voice_pair_ids`** (a fixed `(agent_id, agent_id)` tuple,
persisted): the sole LLM-dialogue pair. `select_voice_pair` picks the 2
most prominent living core-cast members (reuses `_prominence`, the
same ranking `maintain_core_cast` already uses); `maintain_voice_pair`
(called every tick, cheap no-op unless something changed) rotates to
the survivor's strongest remaining core-cast bond if one dies, or picks
an entirely fresh pair if both do — logged as a `voice_pair_change`
event, surfaced with a new 🗣 icon. A pair change clears `voice_
conversation` (a new partner has no business continuing the old
thread).

**`due_for_dialogue` simplified**: no longer partitions core-core vs.
crowd pairs — every colocated pair (including former core-core ones)
now resolves via the deterministic fallback, EXCEPT the exact voice
pair, which is excluded here and scheduled separately via the new
`due_for_voice_dialogue` (its own `VOICE_DIALOGUE_COOLDOWN_TICKS=60`,
far shorter than the ordinary 300 — "call often," since this is now
the only pair spending LLM budget at all). `MAX_LLM_DIALOGUES_PER_TICK`
and the now-dead `_is_significant_pair` LLM-slot prioritizer are
removed — no longer meaningful once there's only ever one LLM-eligible
pair.

**New `llm/dialogue.py` voice-mode prompt/parse path**
(`VOICE_SYSTEM_PROMPT`/`build_voice_prompt`/`parse_voice_dialogue`/
`fallback_voice_dialogue`), deliberately separate from the ordinary
`build_prompt`/`parse_dialogue` (tuned for brief small talk between
people who may barely know each other) rather than a mode flag on it:
- `VOICE_MAX_LINE_WORDS=40` (vs. 26 for ordinary dialogue) — real
  conversation between two people who know each other runs longer.
- `conversation_so_far`: the pair's last `VOICE_CONVERSATION_HISTORY_
  TURNS=6` lines (`Population.voice_conversation`, a new persisted
  ring, `MAX_VOICE_CONVERSATION_STORED=24`), fed back so the model
  continues the actual thread instead of reopening small talk each
  call — the system prompt explicitly instructs this.
- `town_digest`: one concise sentence (current town-brain priority +
  population/season) — deliberately NOT the full grounding apparatus
  (opportunities/beliefs/lexicon/place-names/etc.) ordinary dialogue
  uses, per the explicit "very concise summary" request.
- `internal_state_a`/`_b`: each speaker's own hunger/energy/current
  goal/emotion, one line each.
- The model is never asked for the Phase-2 structured-outcome fields
  (promise/debt/secret/misunderstanding/goal_change) — `parse_voice_
  dialogue`'s return dict carries them at inert defaults so it's a
  drop-in for the SAME shared `_apply_pending_dialogue_results`
  pipeline ordinary dialogue already uses (is_llm-gated event
  surfacing, topic-ring recording, cross-settlement relation nudge —
  reused unchanged, not duplicated).

New `SimulationEngine._schedule_voice_dialogue`/`_run_voice_dialogue`
(mirrors `_schedule_due_dialogue`/`_run_dialogue`'s shape, backpressure/
budget-exhausted ticks degrade to the deterministic fallback same as
every other LLM job) records both lines into `voice_conversation`
regardless of whether the result later resolves via fallback, so the
thread itself always remembers what was actually said.

"Only surface these dialogues in events" was already structurally true
before this change (the `is_llm` event-surfacing gate, v0.73.0) — with
LLM dialogue now concentrated on exactly one pair, this guarantee is
simply sharper: the `dialogue`/`dialogue_surfaced` event categories now
mean, specifically, this one pair's real conversation.

Verified: direct smoke test (initial pair selection, maintain no-op on
an unchanged pair, death-triggered rotation to the survivor's strongest
bond, prompt/parse round trip including a too-long-line rejection),
`scripts/verify_native_soak.py` (2 seeds × 800 ticks) byte-identical.

## [1.3.41] — Living Terrarium batch: laws-of-nature panel, causal threads, time-lapse knowledge counter, ambient seasonal presence

Explicit user follow-up ("Yes do that") on the four items deferred from
v1.3.40 as UI-heavy: 1.5, 3.3, 3.5, 3.6.

**1.5, a visible "law of nature" ontology.** New "⚖ laws of nature"
panel — a filtered, reformatted view over the existing `/knowledge-tree`
data (rule/law/custom/taboo entry types), foregrounding each rule's
real trigger→effect and a "validated"/"untested" badge read from
`TriggerRule.fire_count` (and the secondary side's own last-fired
tick). `World.knowledge_tree()`'s `rule` entries gained `hook_type`/
`fire_count`/`secondary_trigger`/`validated` fields to support this —
"validated" means it has actually fired at least once, never that it's
objectively true, matching the doc's own "some true, some superstition
the sim never validated" framing.

**3.3, legible causal threads (scoped).** A fully generic event-graph
(every event linked to its real cause) would need every event-emission
site threaded with stable ids — out of scope for one batch. Scoped
instead to the one call site that already computes real grounding
facts for a dispute outcome: `_maybe_schedule_dispute`'s apply() now
captures the same souring-level/debt/rival-faction/rival-family/
reputation-gap/law facts already used to build the LLM prompt into a
new `world.ontology.CausalThread` (feud/ostracism/council_ruling
outcomes only — a plain reconcile has no rupture worth tracing). New
`World.causal_threads`/`causal_threads_list()`, `GET /causal-threads`,
and a "🔗 causal threads" panel — click through and see why a feud
actually formed, not just that it did.

**3.5, time-lapse and the returning eye (scoped).** The map-scrubber/
replay/year-reel-export machinery was already fully shipped (v0.65.0,
§5); the new piece is "watch the law-book thicken." Since knowledge-
tree entries are permanent and only ever grow, "how many things were
known as of tick X" is honestly reconstructable from the CURRENT full
tree by counting entries with origination tick `<= X` — no new
per-tick history needed. `loadTimelineIndex` fetches the tree once per
timeline session; `loadTimelineTick` now shows a live "🌳 N things
known so far" line via a binary search over the sorted tick list,
updating as you scrub or replay.

**3.6, ambient generative presence (scoped).** The soundscape half was
already substantially shipped (§6, keyed to weather/night/
temperament); this pass adds Nature's Mind's own strongest-belief
confidence as one more subtle input (a small filter-cutoff nudge) and
ships the genuinely new piece — a faint seasonal color-grade over the
map (`#season-vignette`, a CSS radial-gradient overlay keyed to
`summary.season`, darkening toward winter and lightening through
spring/summer) so the world visibly darkens ahead of a hard winter
without any text announcing it. Era-styled cartography itself was
already shipped (§5 item 5).

Verified: `python3 -c "import hearthmind.simulation.engine; import
hearthmind.interface.app; import hearthmind.interface.api"`, `node
--check app.js`, direct round-trip tests for `CausalThread` and
`TriggerRule.fire_count`, `scripts/verify_native_soak.py` (2 seeds ×
800 ticks) byte-identical.

## [1.3.40] — Living Terrarium batch: composable hooks, species variants, coherence detection, provenance + 4 audit follow-ups

Explicit user request ("Start all of that") over the remaining Living
Terrarium vision-doc items plus four flagged follow-ups from the
v1.3.38 cognition-architecture audit. Scoped down from the full list
(1.1, 1.5, 3.3, 3.5, 3.6, 4.2, 5.3, 5.4 + 4 audit items) to the
backend/data-model-tractable half — 1.5 (visible "law of nature"
ontology), 3.3 (legible causal threads), 3.5 (time-lapse/returning
eye), and 3.6 (ambient generative presence) are all real UI-heavy
efforts better done as their own dedicated batch, deliberately
deferred rather than rushed. See docs/VISION-2026-07-22-LIVINGTERRARIUM.md
for each shipped item's own scoping note.

**1.1, composable hooks (scoped).** A full boolean/AND-NOT combinator
grammar over trigger *state* would need new trigger-recency
infrastructure; shipped a bounded, testable slice instead — a
`TriggerRule` may now bind a SECOND, independent (trigger, hook) pair
alongside its primary one (`ontology.TriggerRule.secondary_trigger`/
`secondary_hook_type`/`secondary_hook_target`/`secondary_magnitude`/
`secondary_last_fired_tick`, each side its own cooldown).
`llm/rule_propose.py`'s prompt/schema/parser extended to let the LLM
propose the secondary side (optional — defaults to empty rather than
falling back to a substitute, since there's nothing to preserve the
weight of for an optional field). `retire_stale_rules` now counts
either side firing as "ever fired."

**4.2, emergent species/variants (scoped).** New `world/wildlife.
SpeciesVariant` registry (id/name/species/herd_id/trait/description)
+ `SPECIES_VARIANT_TRAITS` closed vocabulary (hardier/migratory/timid/
aggressive/prolific) + `llm/species_variant.py` +
`_maybe_schedule_species_variant` (year_end cadence, one un-named
existing herd per firing). Deliberately identity/narrative-only —
`AnimalHerd` has C++-native-index parity requirements (R7); wiring a
variant-conditional numeric stat delta into the native wildlife tick
risks native/fallback divergence and is flagged as real follow-up
work, not silently dropped.

**5.3, coherence/drift detection (scoped).** `_detect_reflection_
pattern` gained an "ontology coherence" branch: once
`REFLECTION_COHERENCE_MIN_TOTAL` (10) concepts exist and
`REFLECTION_COHERENCE_ABANDONED_RATIO` (0.5) of them were abandoned,
this becomes a real Reflection hypothesis through the existing
pipeline. `self_tuning.TUNABLE_GOVERNORS` gained `"ontology
coherence" -> "ontology_proposal_chance"`, consumed as a multiplier
on `_maybe_schedule_ontology_proposal`'s chance calc — a confirmed
hypothesis can genuinely slow the world's own rate of new-concept
proposals. The semantic/qualitative half ("culture drifted into
nonsense") is NOT attempted — needs its own LLM judgment call,
flagged as follow-up.

**5.4, provenance for everything.** `World.knowledge_tree()`'s
entries already carried tick/status/lineage; every entry now also
carries a `"who"` field — a real living agent's name where one
genuinely exists (a concept's inventor, a law's proposing
settlement), a fixed attribution for non-agent origins ("the land
itself" for Nature's beliefs/species variants, "Hearthmind's own
reflection" for hypotheses/conclusions/questions, "Hearthmind itself"
for self-tuning actions), or "the village" where authorship is
genuinely collective. Surfaced in the existing knowledge-tree panel
(`app.js`'s `renderKnowledgeTreeEntry`) — no new panel needed, the
vehicle already existed.

**Audit follow-up: reflection `kind="question"`/`"conclusion"`
entries.** `_reevaluate_reflection_hypotheses` now appends a
deterministic, zero-LLM-cost `kind="conclusion"` notebook entry
(`status="confirmed"`/`"refuted"`, `supersedes` the hypothesis id) at
the exact moment a hypothesis transitions to supported/rejected — a
rejected hypothesis's refutation is now itself a permanent knowledge-
tree entry, not silent. `_maybe_schedule_reflection`'s "pattern
already has an open hypothesis" branch — previously a bare skip —
now asks a genuine open QUESTION about that hypothesis instead
(new `llm/reflection.py` `SYSTEM_PROMPT_QUESTION`/`build_question_
prompt`/`fallback_question`/`parse_question`, new `_maybe_schedule_
reflection_question`) — same year-cadence call slot, zero added LLM
volume.

**Audit follow-up: plan-fulfillment judgment.** `Population.
tick_plans()` previously let an expired `Agent.plan` silently vanish
with no fulfilled/abandoned judgment. Now writes a real memory on
expiry: "a plan resolved (pursued)" if `progress_note` was ever set
during the plan's life, "a plan resolved (abandoned)" if the plan had
a real intent but no progress was ever logged.

**Audit follow-up: relationship-weighted SOCIALIZE targeting.**
`Population`'s SOCIALIZE goal previously picked the plain-nearest
other agent, regardless of any actual relationship — "judgment call
dressed as a heuristic." New `_nearest_liked_agent` (`SOCIALIZE_
RELATIONSHIP_RADIUS=12`, `SOCIALIZE_DISTANCE_PENALTY=0.02`) scores
candidates within radius by `relationship - distance * penalty`,
falling back to the old plain-nearest behavior when the agent has no
relationships yet or none are in range.

**Audit follow-up: genesis-time `Agent.long_term_goal` seeding.**
`llm/mind.py`'s one-time permanent-identity prompt (`_author_one_
mind`, core cast only, fired once per agent's life) now also asks for
an `initial_goal` — new `parse_initial_goal` is deliberately
fallback-less (unlike mind/voice): a missing/empty answer just means
no goal is seeded yet, and the existing monthly life-event-gated job
still forms one naturally later. Applied only when `target.long_term_
goal is None`, so it never overwrites a goal that already formed
some other way, and only on a genuine (non-fallback) LLM answer.

Verified: `python3 -c "import hearthmind.simulation.engine"` after
every edit; `scripts/verify_native_soak.py` (2 seeds × 800 ticks)
byte-identical, run twice across this batch.

## [1.3.39] — Living Terrarium items 4.1/4.3: composite entities + generated sigils

Explicit user request: implement items 4.1 and 4.3 from
docs/VISION-2026-07-22-LIVINGTERRARIUM.md ("New entities and assets,
not just concepts").

**4.1, composite entities from existing primitives:** new `world.
ontology.CompositeEntity` — mechanically nothing more than one real
standing `Building` (unchanged kind/stats — never a new `BuildingKind`)
bound to one real `InventedConcept` via a name and an origin story, the
doc's own "Sorrow-Hall" example (a memorial-shaped building + an
institution_flavor concept, the entity is the sum). New `llm/composite_
entity.py` (same closed-category/hook-vocabulary shape as `llm/
ontology.py`/`llm/rule_propose.py` — a category from `ONTOLOGY_
CATEGORIES`, an optional bounded mechanical hook via the existing
`validate_hook`). `SimulationEngine._maybe_schedule_composite_entity`
(seasonal, round-robin settlement via `_job_target`, `critical=False`
with a real deterministic fallback name) finds the oldest standing
building in the settlement that no entity has named yet
(`_composite_entity_candidate_building`) and grounds the naming prompt
in the settlement's single most notable recent event. `World.
composite_entities` (capped, world-scoped like `invented_concepts`/
`trigger_rules`) also feeds `knowledge_tree()`.

**4.3, generative assets bound to emergent entities:** the parameterized-
SVG path the vision doc itself recommends starting with. New `world/
sigils.py`'s `generate_sigil_svg(name, category)` — fully deterministic
(hashes name+category into a palette/motif/rotation choice, no RNG
state, no LLM call, no heavy model), generated once at composite-entity
creation and stored on `CompositeEntity.sigil_svg`.

Surfaced main-UI (not dev-console — per the standing rule these are
meant to be discovered): the building click inspector shows a named
building's sigil, name, and origin story above the ordinary building
facts (`app.js`'s `renderTargetInspector`, new `latest.composite_
entities` broadcast field); `_diagnostics_snapshot`'s `composite_
entities_total` gives the dev console a raw count.

Verified: direct `_composite_entity_candidate_building` test (finds
the oldest unnamed standing building, correctly excludes an already-
named one on a second call); a direct end-to-end `_maybe_schedule_
composite_entity` test confirming the fallback path names a building,
registers a real `InventedConcept`, generates a sigil, and the entity
survives a `World.to_dict()`/`from_dict()` round-trip;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
(no deterministic tick-state code touched).

## [1.3.38] — Cognition-architecture audit + Living Terrarium items 2.2/3.4

Explicit user request: an audit focused on WHERE cognition should
live, not prompt wording — (1) text-only LLM calls that could update
persistent state, (2) deterministic judgment calls that could become
real LLM cognition, (3) opportunities to extend decision horizon
(plans/goals/experiments/belief revision) over more narration, (4)
fewer-but-more-meaningful calls whose output persists and conditions
later calls, (5) agents/settlement forming hypotheses and carrying
intentions across months/years. Plus: finish a few items from
docs/VISION-2026-07-22-LIVINGTERRARIUM.md.

A research pass across `simulation/engine.py` and every `llm/*.py`
module produced five sections of findings (full text kept in this
session's record, condensed here): confirmed `World.reflection_
notebook` is the only place with a real "am I right about this yet"
evidence loop; found several write-once/read-never LLM outputs
(`culture_digest`/`institution_culture`/`narrative_direction`,
`chronicler` Q&A); found `Agent.plan` silently expires with no
fulfilled/abandoned judgment; confirmed SOCIALIZE targeting and
`_maybe_assign_occupations` are judgment calls dressed as heuristics
that ignore `Agent.relationships`/`trust`/`skills`; confirmed vision
item 2.2 (institutions with persistent goals) was the already-designed
answer to the long-horizon-institution gap. Top follow-ups flagged,
not shipped this pass: `reflection_notebook` `kind="question"`/
`"conclusion"` entries (SELFEVOLVING §5.D/5.E), a plan-fulfillment
check in `Population.tick_plans`, relationship/trust-weighted
SOCIALIZE targeting, an `Agent.long_term_goal` seed at genesis
(`llm/mind.py`).

**Vision item 2.2 shipped (scoped):** `Institution.objective_ticks_
unmet` (`settlement/institutions.py`) tracks how many consecutive
times `compute_objective` re-derives the identical want — a real,
persistent frustration, not a fresh one each check (incremented/reset
in `_maybe_schedule_institution_belief`, zero added LLM volume).
`_maybe_schedule_rule_proposal` now grounds its prompt in whichever
institution has been stuck longest past `INSTITUTION_OBJECTIVE_
PERSISTENCE_THRESHOLD=3`, giving that institution real causal reach
into the Innovation Layer's rule-proposal pipeline — the doc's own
"council remembers a famine legislating against it" case. `rule_
propose.SYSTEM_PROMPT` now asks the model to prefer a rule that
actually responds to a named institutional want when one is given.

**Vision item 3.4 shipped:** new `llm/musing.py` + `World.musings`
(capped at `MUSING_HISTORY_MAX=60` — daily texture, unlike `reflection_
notebook`'s never-pruned discipline) + `SimulationEngine._maybe_
schedule_musing` (day_end cadence, `critical=False`, genuine
deterministic fallback). Grounded in the newest OPEN `reflection_
notebook` hypothesis when one exists, else the newest `knowledge_
tree()` entry, else the call is skipped entirely — no fabricated
musing on a fresh world with nothing yet to say. Surfaced main-UI
(this is explicitly meant to be seen, not dev-console depth): a "💭"
header line reading `World.summary()`'s new `latest_musing` field off
the live broadcast.

Verified: direct `World.to_dict()`/`from_dict()` round-trip for both
`musings` and `Institution.objective_ticks_unmet`; a direct end-to-end
test of `_maybe_schedule_rule_proposal` confirming a stuck institution
grounds the resulting rule and its `rule_originated` log line; a direct
`_musing_subject()` test confirming a fresh world (nothing learned yet)
correctly yields `None`; `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical (no deterministic tick-state code touched).

## [1.3.37] — Enable real reasoning traces for genuine judgment tasks; free their LLM budget

Explicit user directive, table-form: enable reasoning for personal
belief revision, major life decisions, council deliberation, town
consciousness, cultural evolution, and innovation & discovery — keep
it off for dialogue, rumors, dreams, and NPC moment-to-moment
cognition. Change `scripts/run.sh` defaults if required to actually
enable it, and reallocate freed LLM budget toward the tasks that need
real sentience/intelligence — the pillars' own Mind-half tasks and the
game's own self-improvement (Reflection/self-tuning), not just
narration.

**Root blocker found and fixed first:** `scripts/run.sh`'s
`LLAMA_REASONING` defaulted to `off` (`--reasoning-budget 0`,
server-wide) — this silently made every existing `deep_reasoning=True`
job's per-call "detailed thinking on" phrase a no-op regardless of
what the app asked for. Default -> `auto`; `off` still available to
restore the old floor.

**~20 tasks now carry `deep_reasoning=True`** (was 2 — Innovation
Layer propose/evolve only), one flag per the user's table, each tagged
at its call site: `personal_belief`/`beliefs` (personal + settlement
belief revision), `migration_decision`/`fission`/`guild_founding`/
`dispute` (major life decisions), `institution_belief` (council/
family/guild deliberation), `consciousness` (town consciousness),
`tradition`/`religion`/`narrative_direction`/`culture_digest`/
`institution_culture`/`faction`/`laws`/`rule_propose` (cultural
evolution), `invention` (alongside the existing `ontology_proposal`/
`ontology_evolution`, innovation & discovery), `reflection`/
`self_tuning` (the game learning/improving itself — not in the user's
table verbatim but a direct fit for "the game itself to learn and
improve," same Reflection/self-tuning system CLAUDE.md already frames
that way). Dialogue/rumor_interpret/dream/cognition (moment-to-moment
goal decisions) deliberately untouched — already fast, matching the
"off" column. town_brain/era_branch/geography stay untouched too
(already deterministic-decided-plus-LLM-narrated as of v1.3.35 — no
decision left to reason about).

**Schema/reasoning conflict resolved by dropping two schemas, not by
silently keeping reasoning off:** `personal_belief`/`beliefs` were the
only two of the newly-flagged tasks with a `json_schemas.py` grammar —
a grammar enforces the full output shape from the first token, which
suppresses a preceding `<think>` block entirely (`_schedule_llm_job`'s
own structural rule, `reasoning = deep_reasoning and task_schema is
None`, would otherwise silently keep reasoning off for exactly the two
tasks the user named first). Removed both from `TASK_SCHEMAS` — belief
revision benefits more from a real reasoning trace than from strict-
schema enforcement, and `beliefs.parse_*` already tolerated schema-less
output before FT.0 added the grammar.

**Budget reallocation:** `DIALOGUE_BACKPRESSURE_FRACTION` 0.75 -> 0.6,
`RUMOR_INTERPRET_BACKPRESSURE_FRACTION` 0.5 -> 0.35 — pure narration
now sheds its queue slot even earlier under real backlog pressure,
since ~20 tasks now cost 1.5x tokens each (existing `DEEP_REASONING_
NUM_PREDICT_MULT`/`_TEMPERATURE`, unchanged values, now applied far
more broadly) and should get first claim on the shared concurrency
limit.

Verified: direct `_schedule_llm_job` unit test confirming `reasoning=
True`/no schema/boosted num_predict-temperature/correct apply for a
representative newly-flagged task (`beliefs`); a full audit confirming
zero of the ~20 flagged tasks retain a `TASK_SCHEMAS` entry;
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical
(this batch touches only the async LLM-call path, never deterministic
tick state).

## [1.3.36] — Genuine decision-point expansion (migration); Nemotron 3 Nano 4B reasoning support

Explicit user directive, two parts. First: "move the LLM from
describing the world to thinking within the world" — clarified via
follow-up as an audit-driven expansion of which decisions the LLM
makes (not a prompt-wording/person-framing change), classifying each
decision point as deterministic/subjective/hybrid per the user's own
framework and converting hybrid/deterministic judgment calls that are
genuinely subjective into real LLM decisions. This is the opposite
direction from v1.3.35's settlement/civic conversions, which stay
correct — that pass targeted decisions that were actually objective
once the facts were separated out; this pass targets a decision that
is genuinely a judgment call. Second: "optimize all the prompts and
parser to work with Nemotron 3 Nano 4B."

**Individual migration decision** (`llm/migration.py`, new module,
audit's #1-ranked item): a core-cast agent with a real push/pull
reason to leave (bonded partner elsewhere, real hunger next to a
better-fed settlement, overcrowding, standing/feud pressure) used to
migrate on a flat chance roll. Same candidacy/decision split as
`llm/fission.py`/`llm/founding.py`: `Population.migration_push_target`
finds the deterministic preconditions (extracted, unchanged logic,
from the old `_maybe_migrate`); `Population.core_migration_candidates`
scans the core cast only (per-agent LLM decisions stay call-volume-
bounded, standing CLAUDE.md rule); a new engine job (`_maybe_schedule_
migration_decision`, gated by `MIGRATION_CHANCE_PER_TICK`, ambient/
non-critical — a sensible deterministic fallback exists) asks the LLM
to actually weigh the agent's life against the reason, with declining
to leave a real, valid outcome. `Population.depart_for_migration`
carries the extracted mutation logic (settlement reassignment, standing
reset, travel target, memory, relations nudge) unchanged. Non-core-cast
agents keep the original flat-chance-roll path exactly as before.

**Nemotron 3 Nano 4B support** (`llm/client.py`): `Config.llm_model`
default `gemma-4-e4b-it` -> `nemotron-3-nano-4b`. Unlike Gemma
(non-thinking by design), Nemotron 3 is genuinely hybrid-thinking, but
its `<think>` chain-of-thought is controlled purely by an exact
system-prompt phrase ("detailed thinking on"/"detailed thinking off")
that must be the model's first-seen instruction — not an API field.
Both LLM clients' `generate_json` gained a `reasoning: bool = False`
param that prepends the correct phrase (`OllamaClient` also sets its
native `"think"` field to match, for Qwen3 compatibility); harmless
boilerplate for any other model family, sent on every call regardless
of which model is actually loaded. Never combined with `json_schema`
(a grammar enforces the full output shape from the first token,
suppressing a preceding `<think>` block) — `_schedule_llm_job` enforces
this structurally (`reasoning = deep_reasoning and task_schema is
None`), reusing the existing Phase 3.A `deep_reasoning` flag (ontology
propose/evolve, neither of which uses a schema) rather than adding a
new one. `scripts/run.sh`'s `LLAMA_REASONING` doc comment updated to
note Nemotron 3 alongside Qwen3 and flag that a server-wide `off`
default makes this per-call phrase a no-op for `deep_reasoning=True`
jobs unless overridden.

Verified: direct mocked-client tests for both `LlamaCppClient`/
`OllamaClient` reasoning toggle (system-prompt content, Ollama `think`
field), a direct end-to-end migration-decision test (candidacy
detection, job scheduling, apply logic for both depart=True/False),
`scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-identical,
a 4000-tick LLM-disabled engine soak with round-trip equality.

Audit's remaining prioritized items — `choose_building_kind`
(settlement-level, low volume), SOCIALIZE targeting (highest per-tick
call volume; likely needs a non-LLM relationship-weighted heuristic
fix first), `_maybe_assign_occupations` (infrequent per-agent event) —
flagged as follow-up, not attempted this pass.

## [1.3.35] — Deterministic decisions, LLM-authored motivation; diagnostics fixes

Explicit user directive: several settlement/civic decisions were being
asked of the LLM when they should be computed — "the LLM can explain
the motivation afterward." Converts five systems from LLM-decided to
deterministic-decided-plus-LLM-explained, and fixes two diagnostics
gaps.

**Diagnostics.** `/diagnostics`'/dev-console's `llm_model` now reads
the actual `MODEL_PATH` env var (`scripts/run.sh`'s llama-server launch
flag) when set, falling back to `Config.llm_model` only when it isn't
— a live model switch no longer silently drifts from what diagnostics
reports (same root cause class as v1.3.15's `llm_model` default fix,
now closed at the read site instead of just the default). New
`trigger_rules_total`/`trigger_rules_by_status`/`wildfire_ignition_
ticks_recorded` fields close the gap for the two most recent Living
Terrarium systems — `governor_tuning`/`self_tuning_actions_recent`
were already present (v1.3.34) but nothing else from that pass was;
the dev console already dumps the whole `diagnostics` payload as raw
JSON, so any field added here is immediately visible with no frontend
change needed.

**Geography naming** (`llm/geography.py`): fully procedural now, zero
LLM call — a plain weathered place name ("Stillmere", "the Aldwash")
carries no interpretation the LLM would meaningfully add. Reuses the
existing collision-safe fallback pool as the only naming path.

**Era branch** (`llm/era_branch.py`): `compute_branch` scores each of
the five named branches by the settlement's own real STANDING-building
mix (the same `ERA_BRANCH_KIND_WEIGHTS` `choose_building_kind` already
reads), picking the highest — ties favor the sticky current branch,
then a namespaced random pick only when there's genuinely no signal
yet. The one remaining LLM call explains the computed lean in one
sentence; it can no longer choose a different one.

**Town brain priority** (`llm/town_brain.py`): `fallback_priority`
renamed `compute_priority` and promoted from fallback to THE decision
— "Food? Health? Construction? Just compute. Highest wins." Applied
synchronously before any LLM call; `Settlement.current_priority`
reflects it immediately regardless of LLM availability. The job is no
longer `critical` (nothing to defer — the priority is never in
question, only its one-sentence rationale is, and that already has a
real deterministic fallback).

**Institution objectives** (`settlement/institutions.py`): new
`compute_objective` — per-kind deterministic reads (FAMILY: feud
status / household size; COUNCIL: materials shortfall / ambition-vs-
resilience disposition, reusing `town_brain`'s own council-disposition
signal; GUILD: currency shortfall vs. teaching-focus). `Institution.
objective` is set immediately; the institution-belief LLM call (same
call, zero added volume) now only supplies `objective_reason`, an
explanation of the already-decided want, logged as a new
`institution_objective` event.

**Narrative Direction** (`llm/narrative_direction.py`): `compute_
themes` reads `Settlement.mood`'s own real axes (hope/fear/grief/
suspicion — already a statistical aggregate of lived events, Phase I)
and picks the strongest past a real threshold, same signal the old
`fallback_direction` used as its non-LLM path, now THE decision. The
LLM's remaining jobs: a one-sentence summary of the computed theme, and
its one genuinely creative side task (coining a local term for a
dominant event) — unchanged, since naming an unprecedented thing isn't
"choosing among a closed set of moods."

Verified: direct unit tests for every new deterministic function
(`era_branch.compute_branch` tie-breaking, `institutions.compute_
objective` across all three kinds' branches, `narrative_direction.
compute_themes` threshold behavior, `_resolve_llm_model_label`'s
MODEL_PATH precedence), a direct engine-level test confirming `town_
brain`'s priority/rationale/history apply synchronously before the LLM
job resolves, `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
byte-identical, and a 6000-tick LLM-disabled engine soak with full
`World.to_dict()` round-trip equality.

## [1.3.34] — Living Terrarium items 1.4, 2.4: self-tuning, and Reflection that acts

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md's own sequence,
"5. 1.4 + 2.4 — the world tuning and modifying itself, inside
guardrails." The two items are one mechanism: 1.4 is the proposal,
2.4 is the (sandboxed) act.

**The signal.** `World.wildfire_ignition_ticks` (a small capped
rolling window) records the real tick of every wildfire ignition;
`_detect_reflection_pattern` gained a governor-drift branch comparing
the realized mean gap between ignitions against the theoretical gap
`disasters.WILDFIRE_CHANCE_PER_WEEK` implies (`GOVERNOR_DRIFT_RATIO=
2.0`, needs `GOVERNOR_DRIFT_MIN_SAMPLES=5` real ignitions first) — the
vision doc's own worked example ("wildfires feel too rare to matter"),
grounded only in Body state, never a free-text hunch. This is the same
existing Reflection pipeline everything else in Phase 5 uses — a
recurring pattern becomes an open hypothesis, then (via the existing
deterministic `_reevaluate_reflection_hypotheses`) a `supported` one
once it survives multiple year-cadence cycles.

**The proposal (1.4).** New `llm/self_tuning.py`: once a `supported`
hypothesis names a governor in the closed `TUNABLE_GOVERNORS`
vocabulary (`{"wildfire frequency": "wildfire_chance"}` — the only
governor wired to a real mechanical effect so far), one LLM call
proposes a direction (raise/lower) and a magnitude (0..1, a FRACTION of
the allowed band, never a raw value). `disasters.GOVERNOR_TUNING_BAND
=0.3` (±30%) is enforced by `apply_bounded_nudge`, the interpreter
itself — structurally, regardless of what the model asks for.
`tick_wildfire` gained a `chance_multiplier` param reading `World.
governor_tuning.get("wildfire_chance", 1.0)`; `decay_disaster_scars`-
style, this is the second governor items 2.1/2.3 and 1.4 both touch
(disaster_scars via `nature_adaptation_bias`, wildfire ignition via
self-tuning) — deliberately the same low-native-parity-risk module
region.

**The act (2.4).** `SimulationEngine._maybe_schedule_self_tuning`
(world-scoped, year-cadence, `critical=True` — a genuine judgment
about the world's own balance, deferred rather than faked). The
proposed tuning is built on a disposable DEEP-COPIED world (`World.
from_dict`) FIRST — real `World.governor_tuning` is never touched
until `simulation.sandbox.run_counterfactual` confirms the copy
survives 50 ticks without crashing/exploding (item 1.3's sandbox
actually gating a real self-modification, not just rule proposals).
New `World.self_tuning_actions` (append-only, never pruned, same
discipline as `reflection_notebook`) logs every attempt — applied,
rejected by the sandbox, or a deliberate no-op below `SELF_TUNING_MIN_
MAGNITUDE=0.05` — "logged verbosely as the world's own decision,"
exactly as the vision doc asked. A hypothesis is only ever acted on
once (`self_tuning_actions`' own `hypothesis_id`s gate re-firing).
Reflection still never touches Body state directly outside this one
narrow, sandboxed, bounded exception.

**Surfacing.** Dev-console depth, same treatment as `reflection_
notebook` (`_diagnostics_snapshot()` gained `governor_tuning`/`self_
tuning_actions_recent`); an *applied* action also appears in `World.
knowledge_tree()` (new `type: "self_tuning"` entry, 🎛 icon) — visible
in the existing knowledge-tree UI panel alongside every other LLM-
originated persistent decision.

Verified: direct tests for `nature_adaptation_bias`-adjacent
`GOVERNOR_DRIFT_RATIO` detection (no ignitions, severe drift, normal
spacing — each producing the right pattern/no-pattern), `self_tuning.
apply_bounded_nudge`/`parse_self_tuning`, and a full synchronous
pipeline test (seeded `supported` hypothesis -> faked LLM proposal ->
sandbox-validated -> `governor_tuning` mutated for real -> re-firing on
the same hypothesis id correctly skipped). `scripts/verify_native_
soak.py` (2 seeds x 800 ticks) byte-identical — `tick_wildfire` sits in
`World.tick()`'s hot path. A 3000-4000-tick LLM-disabled engine soak
with full `World.to_dict()` round-trip equality, `knowledge_tree()`/
`_diagnostics_snapshot()` both exercised without error.

## [1.3.33] — Living Terrarium items 2.1, 2.3: Nature that adapts and can surprise the Village

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md's own sequence,
"4. 2.1 + 2.3 — Nature that adapts and can surprise the humans."

**2.1, Nature acts on its Mind.** New `terrain_evolution.
nature_adaptation_bias(nature_beliefs)`: the confidence of Nature's
Mind's single strongest belief whose subject concerns repeated fire/
flood/disaster damage (string-matched over `World.nature_beliefs`), or
0.0 if it holds none. `decay_disaster_scars` now takes this as an
`adaptation_bias` parameter and speeds the weekly scar-recovery rate up
to `NATURE_ADAPTATION_DECAY_BONUS_MAX=0.5` (50%) faster once the belief
is confident — the land genuinely recovering faster from repeated
disaster damage it has "paid attention to," bounded and directed by
Nature's own accumulated experience rather than a raw random walk.
Deliberately scoped to disaster scars — the one physical-substrate
module confirmed to have no native C++ counterpart (`apply_disaster_
scars`/`decay_disaster_scars`'s own long-standing R7-deviation note),
so this adds new logic with zero native/fallback parity risk.
`World.tick()`'s existing `decay_disaster_scars` call site now passes
`nature_adaptation_bias(self.nature_beliefs)`.

**2.3, Nature and Village can surprise each other (scoped).** Every
genuinely NEW Nature's-Mind belief (the `else` branch of `_maybe_
schedule_nature_mind`'s apply callback — real fresh insight the land
formed on its own, not a revision of an existing belief) now bumps the
origin settlement's `pattern_signal_counts["nature_adaptation"]` — the
same generic pressure-signal dict `_maybe_schedule_ontology_proposal`'s
`pressured` gate already reads (previously fed only by `dispute_
feud`). A settlement too poor/small to clear the prosperity gate can
now still have its ontology-proposal job made eligible purely by
Nature's own accumulated, unprompted insight — a real Nature-initiated
pressure the Village didn't script, free to originate a custom/law/
ritual/saying in response. Ships the Nature -> Village half of the
loop only; the reverse (a Village action visibly forcing a Nature
adaptation) is flagged as the natural sequel once 2.2 (institution-
driven actions) lands.

Verified: direct tests for `nature_adaptation_bias` (empty list, no
matching subject, matching subject) and the biased decay rate (1.0
bias applies the full 50% bonus, 0.0 bias unchanged), a direct test of
the `pattern_signal_counts` bump shape, `scripts/verify_native_soak.py`
(2 seeds x 800 ticks) byte-identical — `decay_disaster_scars` sits in
`World.tick()`'s hot path even though the function itself isn't
natively ported, so this re-confirms no native/fallback divergence was
introduced — and a 4000-tick LLM-disabled engine soak with full
`World.to_dict()` round-trip equality.

## [1.3.32] — Living Terrarium items 5.1, 5.2: the guardrails

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md's own sequence,
"3. 5.1 + 5.2 — the acceptance auditor and invariant guards. Ship
*before* turning up self-modification, so weeks-long runs stay
coherent."

**5.1, the acceptance gate as a runtime invariant.** New `world.
ontology.retire_stale_rules` + `TRIGGER_RULE_STALE_TICKS=40_000`: an
`active` `TriggerRule` whose trigger has never once matched
(`fire_count == 0`) past the stale window is retired — the concrete
gap this closes, since `InventedConcept` already had this via
`abandon_stale`'s adopter-based staleness but `TriggerRule` (new in
v1.3.31) had no analogous mechanism yet. Called from `_maybe_schedule_
rule_proposal`'s own gated cadence, same precedent as `abandon_stale`'s
call site. Retired, never deleted — same historical-record discipline
as every other status-transition in this registry.

**5.2, invariant guards around self-modification.** Extended
`simulation/sandbox.py`'s `run_counterfactual` (the one place a
proposal's consequences already get checked, rather than a second
parallel gate) with the vision doc's three named invariants:
`POPULATION_HARD_FLOOR` (population reaching exactly 0 is always
unsafe, unconditionally — independent of the existing 50%-loss
fraction check, which could theoretically miss a small-population edge
case) and `RESOURCE_EXPLOSION_MULTIPLE=5.0` (total settlement
materials exploding beyond 5x starting value). "No governor can be
disabled" is satisfied structurally rather than by a new runtime
check: a `TriggerRule`'s `hook_type` is drawn from the closed
`MECHANICAL_HOOK_TYPES` vocabulary, none of which reads or writes
`Config` — there's no vector through which a proposal could reach a
governor at all.

Verified: direct tests for `retire_stale_rules` (a never-fired rule
retires past the window, a once-fired rule doesn't), the sandbox's new
extinction/resource checks (including the edge case of an
already-extinct world not being falsely flagged as newly-caused),
`scripts/verify_native_soak.py` byte-identical, a 6000-tick
LLM-disabled engine soak with round-trip equality.

## [1.3.31] — Living Terrarium items 3.1, 1.2, 1.3

Continues docs/VISION-2026-07-22-LIVINGTERRARIUM.md down its own
stated priority sequence: "1. 3.1 + 3.2 ... 2. 1.2 + 1.3."

**3.1, "the morning paper".** The away-digest gained a structured
"front page" section alongside its existing prose recap:
`World.away_digest_highlights` is every `knowledge_tree()` entry
originated strictly after the digest's own `since_tick` window — what
the world originated for itself while the observer was away — computed
in the same `apply` callback at zero extra LLM cost (a pure read over
already-computed state). `GET /digest` now returns a `highlights`
array; the digest panel renders it under the headline using the same
entry renderer the knowledge-tree panel uses (hoisted above both so
they share it, not duplicated).

**1.2, "a conditional/trigger vocabulary as data".** New `world.
ontology.TriggerRule` (+ `TRIGGER_TYPES`: on_death/on_birth/on_feud/
on_invention/on_drought/on_surplus) — a village-originated rule binding
a real trigger to a real mechanical hook (reuses `MECHANICAL_HOOK_
TYPES`/`validate_hook` verbatim, same closed-vocabulary discipline as
`InventedConcept`). New `llm/rule_propose.py` +
`SimulationEngine._maybe_schedule_rule_proposal` (season_end, world-
scoped, round-robins settlements like the ontology-proposal job).
Firing is wired to each trigger's real, pre-existing detection point:
`on_death`/`on_birth` off `World.last_life_events`, `on_feud` off
`llm.dispute`'s feud outcome, `on_invention` off a genuine invention
forming, `on_drought`/`on_surplus` off a new low->high edge-detected
crossing of `World.disasters.heat_pressure`/a settlement's granary
fill fraction (transient per-settlement previous-state tracking,
`_prev_drought_state`/`_prev_surplus_state`). `TRIGGER_RULE_COOLDOWN_
TICKS=500` prevents a burst of matching events from turning one rule
into runaway repeated narration. Only `belief_confidence_bonus` is
actually consumed as a real numeric effect this pass — the other hook
types stay narrative-only, flagged not silently dropped (same honesty
as `InventedConcept`'s own not-yet-consumed hook types, a pre-existing
gap this pass did not attempt to close). Rules surface in the
knowledge tree (new `type: "rule"`, ⚙ icon).

**1.3, the counterfactual sandbox.** New `simulation/sandbox.py`'s
`run_counterfactual`: before a proposed rule goes live, deep-copies the
world via its own `to_dict`/`from_dict` round trip, runs the fork
forward 50 ticks with the LLM forced off (a physics/invariant check,
not a cognition test), and checks it doesn't crash (population loses
>50%) or explode (population >3x) — the two invariants the vision doc
names concretely. An unsafe proposal is discarded and logged
(`trigger_rule_rejected`), never silently dropped. Properly cancels and
awaits the fork's own background LLM-fallback tasks before closing its
throwaway in-memory DB connection (caught live during verification —
an early version left a dangling task writing to an already-closed
connection). Runtime-invariant floors/ceilings as a standing guardrail
(item 5.2) and coherence/drift detection (item 5.3) remain separate,
larger, unattempted vision-doc items.

Verified: direct tests for digest highlights (window correctness across
two consecutive requests), trigger detection + cooldown (direct calls,
same-tick re-fire suppression), the full rule-proposal ->
sandbox -> registration pipeline end-to-end with a fake LLM client, the
sandbox's isolation from the real world (population/tick unchanged
after a sandboxed run) and its background-task cleanup fix,
`scripts/verify_native_soak.py` byte-identical (no native module
touched), an 8000-tick and a 15000-tick LLM-disabled engine soak with
round-trip equality.

## [1.3.30] — The Living Terrarium vision doc + item 3.2 (knowledge tree)

New docs/VISION-2026-07-22-LIVINGTERRARIUM.md (user-uploaded, filed as
the next-frontier vision doc following docs/VISION-2026-07-21-
SELFEVOLVING.md's pattern): maps five capabilities toward a "living
terrarium" — self-modifying mechanics (composable/trigger hooks +
counterfactual sandbox + bounded self-tuning), Nature/institutions as
true participants, the daily-peek experience, new entities/assets, and
runtime safety guardrails. Confidence-tagged [CERTAIN]/[LIKELY]/
[CREATIVE]; ships its own priority sequence.

This pass: item 3.2, "What the world learned" ledger — [CERTAIN],
first in the doc's stated sequence, "mostly surfacing data that
already exists." New `World.knowledge_tree(limit=200)`: a single,
newest-first, read-only aggregation of every LLM-originated persistent
entity across all four pillars plus Reflection — `invented_concepts`
(with `lineage`), each settlement's `laws` (law/custom/taboo),
`reflection_notebook` hypotheses (status/confidence), and `nature_
beliefs` — no new state, no new LLM call, each underlying store
already independently capped. Reached via a new on-demand provider
hook (`WorldBroadcaster.set_knowledge_tree_provider`/`get_knowledge_
tree`, same shape as the existing `full_diagnostics` provider) and
`GET /knowledge-tree`. New "🌳 knowledge tree" panel in the explore
menu, same toggle/fetch/render pattern as the existing highlights
panel — lineage rendered inline ("evolved from #N" / "merged from
#N + #N") when present.

Verified: direct aggregation/sort/lineage tests, a round-trip
(`to_dict`/`from_dict`) equality check, an end-to-end FastAPI
`TestClient` request through the real provider chain, a JS syntax
check, `scripts/verify_native_soak.py` byte-identical (no native
module touched), a 500-tick LLM-disabled engine run with round-trip
equality. The doc's remaining items (3.1 "morning paper," the
1.x self-modification frontier, 2.x Nature/institution agency, 4.x/5.x)
are recorded as open in the vision doc itself — not attempted this
pass, picked up on future explicit direction per this project's
"smallest coherent milestone" discipline.

## [1.3.29] — LLM integration architecture audit

Explicit user directive: audit every LLM call site, classify what each
one does (dialogue/planning/narration/cognition/other), and refactor
only where necessary so every LLM interaction passes through a single
cognition interface, without changing gameplay.

**Finding: the unification mostly already existed.** `_schedule_llm_
job` (engine.py, established the "July 2026 architecture review §1.2"
collapse of ~10 hand-rolled `_run_X` coroutines into one shared runner)
is already the single interface ~30 settlement/world-scoped jobs go
through — budget consume, backpressure pre-check convention, JSON-
schema-constrained decoding, critical-vs-ambient fallback discipline,
debug/call recording, all centralized. Three call sites bypassed it:
`_run_cognition` (per-agent goals) and `_run_dialogue` (per-pair
dialogue) are documented, structurally-necessary exceptions — both
carry pending-result queues and staleness handling `_schedule_llm_
job`'s fire-and-immediate-apply shape doesn't need. `_maybe_interpret_
rumor` had no such justification: it duplicated `_schedule_llm_job`'s
budget-consume/debug-record/call-record bookkeeping in a hand-rolled
`_runner()` coroutine for no structural reason.

**The one refactor**: `_maybe_interpret_rumor` now builds its prompt/
fallback and calls `_schedule_llm_job` like every other settlement job,
keeping its own tighter backpressure fraction check as an explicit
pre-check (same pattern every other job's `_settlement_job_
backpressured()` pre-check already uses). One deliberate, documented
behavior change: on a day whose LLM budget is already spent, this used
to skip the rumor retelling entirely (silent no-op); now it applies the
deterministic fallback retelling, matching every other non-critical
job's convention instead of being the one outlier that silently drops
its ambient texture. `server.py`'s one-shot world-genesis call and
`llm/rejection_sampling.py`'s standalone offline training tool are both
legitimate, out-of-scope exceptions (no engine/World exists yet for the
former; not part of the live tick loop for the latter) — left as-is.

Verified: direct end-to-end test (FakeClient) confirming memory
formation and counters unchanged through the new path,
`scripts/verify_native_soak.py` byte-identical (no native module
touched), a 6000-tick LLM-disabled engine soak with round-trip
equality. Files changed: `hearthmind/simulation/engine.py` only.

Explicit user directive: "Start the 5th item and extend LLM 4-5
pillars." Reflection is a meta-cognitive system observing the four
Minds (Humans, Village, Nature, Innovation), not a fifth pillar — see
v1.3.27's Body/Mind correction. Ships 5.A (persistent research
notebook) and 5.B (the reflection job) only; 5.C (counterfactual
sandbox), 5.D/5.E (prompt/architectural self-improvement) remain
design-only, flagged not attempted this pass.

New `World.reflection_notebook`/`next_reflection_entry_id`: typed
`ReflectionEntry` records (`kind: observation|hypothesis|experiment|
conclusion|question`, `subject`, `content`, `confidence`,
`evidence_for`/`evidence_against`, `status: open|supported|rejected|
superseded`, `supersedes`), never pruned by design — a rejected
hypothesis stays as historical knowledge, not deleted.

New `llm/reflection.py` + `SimulationEngine._maybe_schedule_reflection`
(world-scoped, `season_end`, `critical=False` — ambient self-
improvement, not blocking cognition, keeps a real deterministic
fallback). Each firing: (1) `_detect_reflection_pattern` — a
deterministic pass reusing existing counters across all four pillars,
no new instrumentation beyond one read-only aggregate: `Settlement.
pattern_signal_counts` (Village/Human), `WildlifeGrid.summary()`'s
`prey_scarce`/`predator_pressure_ratio` (Nature), and established-
concept category-imbalance over `world.invented_concepts` (Innovation/
cross-pillar, new `REFLECTION_ONTOLOGY_IMBALANCE_MIN_TOTAL=6`/
`_RATIO=3.0`); (2) if a pattern clears threshold and no open hypothesis
already shares its subject, one LLM call proposes a grounded hypothesis
plus explicit "what would contradict it" evidence, written as a new
notebook entry; (3) `_reevaluate_reflection_hypotheses` — every
existing OPEN hypothesis gets a small bounded confidence nudge
(`REFLECTION_CONFIDENCE_STEP=0.08`) from fresh evidence, transitioning
to `supported`/`rejected` at `REFLECTION_SUPPORTED_THRESHOLD=0.85`/
`REFLECTION_REJECTED_THRESHOLD=0.15`, no LLM call. Surfaced via
`_diagnostics_snapshot()` (`reflection_notebook_total`, `_by_status`,
`_recent`) — dev-console/raw-JSON only, matching Phase G/consciousness
precedent for internals-depth content.

Verified: direct production-path tests (hypothesis formation with a
FakeClient, multi-cycle confidence-nudge/dedup showing exactly 1
notebook entry persists across 3 firing cycles despite the pattern
recurring, ontology-imbalance detection, critical-job-deferral N/A
since `critical=False`), a 6000-tick engine soak + round-trip equality,
`scripts/verify_native_soak.py` byte-identical (no native module
touched).

## [1.3.27] — Body/Mind architecture correction + Nature's Mind

Explicit user correction: stop describing the LLM as a layer "bolted
on to" deterministic simulation — each pillar (Humans, Village, Nature,
Innovation) is one system with two inseparable halves: Body
(deterministic, always-authoritative objective reality) and Mind (LLM,
that pillar's subjective cognition — perception, memory interpretation,
belief formation, goal/social/cultural reasoning, concept invention).
A pillar with a thin Mind is incomplete, not correctly-mostly-
deterministic-by-design. Reflection is not a fifth pillar — it's the
meta-cognitive system observing the four Minds, one level up, never
touching Body state directly. Full text: docs/VISION-2026-07-21-
SELFEVOLVING.md's new "v1.2 revision note"; summarized as a standing
rule in CLAUDE.md's design-priorities section.

**Follow-up correction, same session: the shared ontology is a cross-
pillar capability, not an Innovation subsystem.** Every pillar should
originate its own kind of first-class entity into the SAME `world.
ontology.InventedConcept` registry — Humans (customs/professions/
myths/traditions), Village (institutions/laws/festivals/political
structures), Nature (ecological relationships/migration routes/
habitats/climate phenomena), Innovation (technologies/philosophies/
theories) — so any system can discover/combine/reinterpret/evolve/
merge across origins indefinitely. `ONTOLOGY_CATEGORIES` already spans
all four pillars' flavors, but scheduling had collapsed to one
mechanism: `_maybe_schedule_ontology_proposal` let the LLM pick ANY of
the eight categories from a single settlement-prosperity-gated
"village imagination" job — meaning even an `ecological` concept was,
in practice, Village-originated.

**Closed this pass: Nature's Mind (the identified gap) + the ontology
fix together.** New `llm/nature_mind.py` + `SimulationEngine._maybe_
schedule_nature_mind` — world-scoped, `season_end` cadence, `critical=
True` (deferred, never fabricated, on a spent budget/failed call, same
discipline as settlement beliefs). Grounded ONLY in Nature's own Body
state: `WildlifeGrid.summary()`'s trophic-pressure ratios (3.D),
`World.disaster_scars`/`mining_scars` counts, `World.fallow_ticks`
(succession progress, 3.D), `World.climate`'s warming/drying trend,
season — never settlement prosperity/era/tech level. One combined LLM
call does two things (same "maximize emergence per call" discipline):
(1) forms/revises a belief in new `World.nature_beliefs` (same shape/
discipline as `Settlement.beliefs`, reuses `llm.beliefs.parse_belief`/
`is_noop_belief_revision`); (2) may originate one new `category=
"ecological"` concept into the shared registry. `llm/ontology.py`'s new
`VILLAGE_PROPOSE_CATEGORIES` narrows the Village-imagination job to the
other seven categories — `ecological` is now `nature_mind`'s exclusive
territory — and `parse_propose` deterministically redirects a
hallucinated `ecological` answer back to a real Village category.

Not attempted this pass (flagged, real future scope): Nature's Mind
doesn't yet feed back into the Body mechanically (Village's `current_
priority` does, via `choose_building_kind`); a genuine Human-vs-Village
ontology-origination split (both still route through the same Village
job today).

Surfaced: `World.summary()`'s `nature_beliefs`, a new "The land's own
sense" stat tile in app.js.

Verified: direct unit tests (belief formation + concept origination
through the real production `_schedule_llm_job` path with a fake
client; correct critical-job deferral with the LLM disabled — state
left untouched, `calls_deferred_critical` incremented, nothing
fabricated), category-redirect test for the narrowed Village-imagination
job, a 6000-tick LLM-disabled engine soak with round-trip `to_dict()`/
`from_dict()` equality, `scripts/verify_native_soak.py` (2 seeds x
800 ticks) byte-identical — no native module touched.

## [1.3.26] — Phase 3.D food webs / predator-prey feedback

Explicit user request: "continue with food webs and predator-prey
feedback" — the last open item in docs/VISION-2026-07-21-
SELFEVOLVING.md's Phase 3.D.

`world/wildlife.py`'s hunt/starve mechanic already had a real local
loop (a predator pack only reproduces on a successful same-tile hunt,
and starves out without one) — the actual gap was that it was purely
local: a pack that happened to land on prey bred normally even while
the map-wide grazer population was collapsing, and a herd bred at its
normal rate even under heavy predation pressure it hadn't personally
been hunted by yet.

`WildlifeGrid.tick()` now computes two cheap aggregate ratios once per
tick (R7 deviation — Python, an O(n) scalar reduction over the herd
dict the tick loop already iterates, not a new per-tile hot loop, same
precedent as the mining/disaster-scar and soil-fertility modules):
`predator_pressure_ratio` (total predator animals / total grazer
animals) crossing `PREDATOR_PRESSURE_RATIO_THRESHOLD=0.25` halves
grazer reproduction chance map-wide (`PREDATOR_PRESSURE_REPRODUCE_
PENALTY=0.5`) — a "landscape of fear" effect distinct from the direct
kills the existing hunt mechanic already applies. `prey_scarce`
(current grazer-herd-count below `PREY_SCARCITY_RATIO_THRESHOLD=0.5`
of world-gen's own expected support, `GRAZER_TO_PREDATOR_RATIO` herds
per pack) halves predator reproduction chance
(`PREY_SCARCITY_REPRODUCE_PENALTY`) and doubles starvation risk
(`PREY_SCARCITY_STARVE_MULTIPLIER`) even for a pack that got a lucky
same-tile hunt this exact tick. Both ratios are surfaced in
`WildlifeGrid.summary()` and the "Wildlife" stat tile (a "prey
scarce"/"heavy predation" suffix, plus an updated tooltip explaining
the loop).

River course drift and ecology->weather bidirectional feedback remain
flagged, not attempted — the doc's own §3.D scope was food webs +
succession + scars; succession and scars already shipped (v1.3.22/
v1.3.25), this closes food webs, the last of the three.

Verified: direct unit tests exercising both directions of the loop in
isolation (heavy-predation-suppresses-grazer-breeding,
prey-scarcity-suppresses-predator-breeding-and-raises-starvation), an
8000-tick LLM-disabled engine soak sampling `wildlife.summary()` every
2000 ticks (stable, non-collapsing populations throughout) with a
round-trip `to_dict()`/`from_dict()` equality check,
`scripts/verify_native_soak.py` (2 seeds x 2500 ticks) byte-identical.

## [1.3.25] — Phase 3.C architecture + Phase 3.D succession

Explicit user request: "continue with 3.C and 3.D" — the two remaining
open items from docs/VISION-2026-07-21-SELFEVOLVING.md's Phase 3
second slice.

**3.C: architecture visibly changing on the map.** New `world/
ontology.py` `ARCHITECTURE_RELEVANT_CATEGORIES = ("technology",
"institution_flavor")` and `dominant_architecture_concept(world,
settlement_id)` — a settlement's own most-recently-established concept
(by `tick_invented`) in one of the two categories that plausibly
reshape what gets built, or `None`. `SimulationEngine._maybe_broadcast`
now computes `architecture_styles` (per-settlement `{name, category,
concept_id}`) and tags each broadcast building with its `settlement_id`
(broadcast-only, not persisted on `Building`). `app.js` outlines a
settlement's buildings in a color hashed from the concept id
(`architectureStyleColor`) instead of the flat default border, and
building hover tooltips name the style when one exists. No established
architecture-relevant concept yet -> unchanged rendering.

**3.D: forest succession, real intermediate stages.** `maybe_reclaim`
previously flipped an eligible abandoned-grassland tile straight to
forest the first week it qualified — no gradual regrowth. New `World.
fallow_ticks` (same additive-Python-dict-overlay shape as `mining_
scars`/`disaster_scars`, same R7-deviation rationale) tracks
consecutive qualifying weeks per tile via `terrain_evolution._tick_
fallow`; only a tile fallow for `REFOREST_MIN_FALLOW_WEEKS=3`
consecutive weeks is even offered to the existing roll, and a tile that
stops qualifying resets to 0 rather than pausing. Caught and fixed a
real native-vs-fallback divergence while verifying: the Python fallback
originally iterated the eligible-tile set in undefined hash order,
drawing RNG rolls in a different order than the native path's row-major
scan — fixed by sorting the fallback's iteration into the same
`(y, x)` order the native path implicitly uses.

Flagged, not attempted this pass (real remaining scope, not silently
dropped): food webs / predator-prey trophic feedback (`world/
wildlife.py`), river course drift (rivers are static geometry in
`world/hydrology.py`, not a per-tile biome the reclaim/scar machinery
can extend into), and ecology->weather bidirectional feedback
(flagged `[HYPOTHESIS]`, needs a reachability check against existing
spatial-weather smoothing first).

Verified: direct smoke tests (dominant-concept selection, payload
construction, round-trip `World.to_dict()`/`from_dict()` equality for
`fallow_ticks`), a live `SimulationEngine._maybe_broadcast` run through
a real asyncio loop confirming `architecture_styles`/`buildings[].
settlement_id` reach the actual broadcast payload, a 6000-tick
LLM-disabled engine soak, `scripts/verify_native_soak.py` (2 seeds x
2500 ticks, plus a re-run at 800 ticks) byte-identical after the
ordering fix above.

## [1.3.24] — Phase 3.A adoption thresholds + Phase 4 initial audit

Explicit user request: "start both" — Phase 3's last open 3.A item
plus starting Phase 4 (cross-pillar audit + persistence
generalization), docs/VISION-2026-07-21-SELFEVOLVING.md.

**3.A: population-scaled adoption thresholds.** `world/ontology.py`'s
`maybe_promote_status` now scales its spreading/established thresholds
against the concept's origin settlement's actual core-cast headcount
(`CONCEPT_SPREADING_FRACTION=0.2`/`CONCEPT_ESTABLISHED_FRACTION=0.5`),
floored at the original flat values so a small/new core cast still
promotes at the original pace. Core-cast headcount, not total
settlement population, since only core-cast members can ever become
tracked adopters (`_maybe_spread_concepts`'s existing candidate
filter) — scaling against unreachable population would have made
large settlements' concepts nearly impossible to promote.

**Phase 4 initial audit pass.** Spot-checked representative wiring
across all three cross-pillar directions (Nature<->Human, Village<->
Human, Nature<->Village) — no code gap found, consistent with the
audit's own "expected to be small" framing; findings documented in the
vision doc's Phase 4 section. Persistence-generalization item audited
and resolved as "already consistent by design, no new mechanism
needed": the Tier 0.1 decay-lock convention exists specifically
because interpersonal rupture has a "should never silently heal"
intent, the opposite of disasters/landscape-scars' deliberate "nature
recovers if left alone" intent — applying a lock there would
contradict the mechanic's own purpose. Village-identity fields
(`current_priority`/`era_branch`/`recent_topics`) checked for
unintended erosion and found clean — none have any decay mechanic,
persisting until their own owning job overwrites them.

Verified: direct smoke tests for `maybe_promote_status`'s scaling
(small vs. large core cast), `scripts/verify_native_soak.py` (2 seeds
x 3000 ticks) byte-identical — the audit pass made no code changes
beyond the 3.A threshold fix.

## [1.3.23] — Phase 3.B remaining items: occupation-as-status, dialogue register, deeper inheritance

Explicit user follow-up ("continue"): closes 3.B's two remaining
unshipped items (occupation → identity/status/dialogue register,
deeper inheritance) from docs/VISION-2026-07-21-SELFEVOLVING.md.

New `agents/occupations.py` constants: `OCCUPATION_STATUS_BONUS`
(mayor/priest only) feeds directly into `Population._prominence` — the
"positive counterpart" to `Agent.standing_penalty`'s ostracism-only
negative signal, consumed by the same council-eligibility ranking and
core-cast refill `_prominence` already drives. `OCCUPATION_DIALOGUE_
REGISTER` (priest/banker/mayor/teacher/scribe) is a light manner-of-
speaking hint in `dialogue.build_prompt` — "a priest speaks to belief,
a banker to debt," the doc's own example — same "garnish, never
forced" treatment `voice` already gets; every other occupation is a
genuine no-op. Rivalry between same-occupation agents sharing a
building/market (the doc's third occupation-status bullet) is
deliberately NOT attempted this pass — it needs a real colocation-
detection mechanism that doesn't exist yet, flagged as a future
follow-up rather than faked.

Deeper inheritance: `Population._apply_inheritance` gained a personal-
belief transfer, same imperfect-transmission shape v0.87.0's lesson
inheritance already established — the deceased's freshest `Agent.
beliefs` entry passes to the heir at `INHERITANCE_BELIEF_CHANCE=0.4`,
attributed ("X used to believe...") and at reduced confidence
(`INHERITANCE_BELIEF_CONFIDENCE_FRACTION=0.6`) rather than claimed as
the heir's own hard-won theory.

Verified: direct smoke tests (status bonus in `_prominence`, dialogue
register text, belief-inheritance transfer shape), a clean 5000-tick
LLM-disabled engine run with round-trip byte-equality,
`scripts/verify_native_soak.py` (2 seeds x 3000 ticks) byte-identical.

## [1.3.22] — Phase 2 completion, Phase 3 first slice (3.A/3.B/3.D)

Explicit user request: "complete phase 2 and start phase 3" —
docs/VISION-2026-07-21-SELFEVOLVING.md.

**Phase 2 completion.** Item 4 ("continuation weeks later"):
`_is_significant_pair` (dialogue's LLM-slot prioritizer) now also
treats an open ledger promise between the pair as significant, so a
pair with an unresolved thread genuinely competes for the next LLM
slot instead of only surfacing incidentally. Item 5 (voice consumed
more consistently): `llm/letters.py`'s prompt now reads `agent.voice`
the same way `dialogue.py` already does — a letter is first-person
written speech from a specific agent, the same "speaking as
themselves" shape.

**Phase 3 first slice** (one load-bearing mechanism per pillar, same
discipline as Phase 1):

- **3.A Innovation, "reserved deeper reasoning"**: both LLM clients'
  `generate_json` gained optional `num_predict_override`/`temperature_
  override` params, threaded through `CognitionRunner.run` and
  `_schedule_llm_job`'s new `deep_reasoning=True` flag — applied only
  to the Innovation Layer's propose/evolve/merge calls
  (`DEEP_REASONING_NUM_PREDICT_MULT=1.5`, `DEEP_REASONING_
  TEMPERATURE=0.5`), every other job's generation config unaffected.
- **3.B Humans, irreversible personality shift**: new `Agent.hardened_
  traits`/`extreme_event_count`, `Population._maybe_harden_trait`.
  Three extreme-event triggers (surviving a disaster from 1.D, a
  feud/ostracism outcome hardening, widowhood) increment a counter;
  crossing `EXTREME_EVENT_HARDEN_THRESHOLD=3` locks TRAIT_RESILIENCE
  into `hardened_traits` (exempt from `_tick_traits`'s monthly
  reversion from then on) with one real, permanent bump.
- **3.C Village**: audited, not further built — `known_concepts`
  (1.A) and `recent_goal_counts` (1.C) already ground every town_brain
  call with accumulated NPC/Innovation history. The map-rendering half
  (architecture visibly differing per established concept) needs live
  design judgment, not a mechanical extension — flagged as a future
  follow-up rather than built speculatively this pass.
- **3.D Nature, permanent landscape scars**: new `World.disaster_
  scars` + `world/terrain_evolution.py`'s `apply_disaster_scars`/
  `decay_disaster_scars` — same shape as `mining_scars` (cosmetic-only
  intensity, same R7-deviation rationale: Python, not yet worth a
  native port). A tile actively flooded/burning gains scar intensity
  each tick, decays weekly if left alone. Food-web/succession/
  weather-ecology items in 3.D remain open, not attempted this pass.

Full UI-surfacing pass in the same batch per the standing workflow
rule: a `disaster_scarred` map overlay (`paintDisasterScars`, distinct
ashen tint from mining's dark-pit color) and a "Disaster scars" stat
tile, both mirroring `mining_scars`' existing treatment exactly.

Verified: direct smoke tests for every new mechanic (client generation-
config overrides, trait hardening + reversion-exemption + round-trip,
disaster-scar gain/threshold-event/decay), a clean 5000-tick
LLM-disabled engine run with a full to_dict/from_dict round-trip
byte-equality check, `scripts/verify_native_soak.py` (2 seeds x 3000
ticks) byte-identical, and a Node.js syntax check on the modified
frontend file.


---

**Older entries (everything before the version above) have been moved to [docs/CHANGELOG-ARCHIVE.md](docs/CHANGELOG-ARCHIVE.md) to keep this file readable** — full detail preserved there, nothing lost.
