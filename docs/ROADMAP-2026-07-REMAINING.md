# Hearthmind — Remaining Work Roadmap (filed v1.28.0)

Explicit user request: "build an updated roadmap to implement all the
features from all parts that you deferred for later and did not
implement in the first pass. This includes porting to C++ as well."

**Scope note, updated:** this document now covers **Part A (the
deterministic Body, det_sys.md's 25 items), Part B (the cognitive Mind,
LLM_Pillars.md's five pillars), Part C (the Body↔Mind seam), and the
C++ native-porting backlog** — all four sections of `docs/
MASTERCHECKLIST-2026-07-22.md`. (The first filing of this document
covered Part A + C++ only, on my own judgment call that B/C looked
substantially shipped from CLAUDE.md's history — not something the user
asked for. Corrected on request: B/C are shipped-a-first-version in
most places, not fully closed, and the actual open items are worth
recording just like Part A's.) Vision/audit docs outside the Master
Checklist (`docs/VISION-*`, `docs/IDEAS-2026-07-EMERGENCE.md`, `docs/
AUDIT-2026-07-20.md`) remain out of scope — each already internally
marked "fully resolved" or "historical record" per CLAUDE.md. As of
v1.34.2, `docs/HEARTHBENCH-RUNTIME-2026-07-23.md` (a separately
uploaded checklist, HearthBench model-benchmarking + the Adaptive
Runtime) is explicitly folded in as this doc's own **Tier 5** — see
the priority-ordering section below.

Every item below is a **real gap**, quoted or closely paraphrased from
the Master Checklist's own "still open" language as of this filing —
nothing here is guessed. Where a status changed mid-session (A3, A20,
A21), that's already reflected. Standing convention carries over
unchanged: work from this doc only on a future explicit "next
step"/item-naming instruction, never auto-chained.

---

## Priority ordering (this document's own read, not gospel)

Ranked by two things: (1) how many *other* open items each one unblocks
(a substrate item like A1/A11's remaining scope, or A9's feedback-loop
discipline, pays off repeatedly), and (2) how directly it serves the
project's own stated top priority, **emergence**. Sequencing inside a
tier is arbitrary.

**Tier 0 — the single biggest lever in the whole document**
0. **B1/B2/B3/B7's shared open half: refactor the ~55 scattered LLM
   jobs into real acts of the five pillars.** Every one of B1/B2/B3/B7
   is marked "shipped" today on the strength of exactly ONE
   representative job per pillar (Village=beliefs, Humans=narrative_
   direction, Nature=nature_mind, Innovation=ontology_proposal,
   Reflection=reflection) — the other ~50 LLM call sites in the
   codebase (dialogue, chronicle, dispute, founding, omens, culture
   jobs, etc.) still run exactly as they did before the pillar
   abstraction existed, untouched by observe/interpret cycling,
   attention-budget arbitration, or inbox/outbox messaging. This is
   the actual "five conscious minds inhabiting the Body" vision, not
   "five extra fields bolted onto business as usual." Bigger than any
   single Part A item; sequence it whenever a real multi-week push is
   available, not as a quick follow-up.

   **First slice shipped, v1.32.0**: a SECOND real production job per
   pillar now mirrors into `world_model`/`memory` (invention ->
   Innovation, self_tuning -> Reflection, institution_belief ->
   Village, dream -> Humans, memory-only). 2 of ~55 jobs/pillar wired
   per pillar now, not 1 — real progress, nowhere near closed.

   **Second slice shipped, v1.33.0**: a THIRD job per pillar for four
   of the five (ontology_evolution -> Innovation, species_variant ->
   Nature, dispute -> Village memory-only, migration_decision ->
   Humans memory-only; Reflection stayed at 2 that pass — flagged
   `_maybe_schedule_reflection_question` as "part of the same job as
   `reflection`," which on closer look in the next pass turned out
   wrong: it's its own distinct `_schedule_llm_job` call site).

   **Third slice shipped, v1.34.6**: Reflection's real third job
   (`reflection_question` -> memory-only, correcting v1.33.0's own
   misjudgment above) and Village's fourth (`rule_propose` ->
   `world_model` observation + memory). Nature stays at 2 — still no
   obvious third candidate. A real pre-existing bug (`_musing_
   subject()` not filtering `reflection_notebook` entries by `kind`,
   crashing on a `"question"` entry's `confidence=None`) was found and
   fixed while verifying this slice.

   **Fourth slice shipped, v1.34.7**: Humans' fourth job
   (`memory_drift` -> memory-only). Nature checked again for a third
   candidate; `omen` is the closest by content but explicitly sits
   under Phase G's ambiguity discipline (never confirm anything) —
   a pillar `world_model` entry's status field would violate that,
   so it was deliberately left unmirrored rather than forced.

   **Fifth slice shipped, v1.34.8**: Innovation's fourth job
   (`composite_entity` -> `world_model` observation + memory).

   **Sixth slice shipped, v1.34.9**: Nature's third job (`omen` ->
   `world_model` hypothesis + memory) — asked the user directly via
   `AskUserQuestion` about the flagged Phase G conflict (an omen
   world_model entry's status field would "confirm" something, which
   Phase G forbids); explicit answer: "ignore phase G for this one
   completely." Scoped narrowly to this ONE mirror site — every other
   omen consumer (stat tile, dev console, narration) is untouched and
   stays exactly as ambiguous as before.

   **Seventh/eighth slice shipped, v1.34.10**: Village's fifth job
   (`laws` -> `world_model` observation + memory — a newly-enacted
   law/custom/taboo is a real settled civic fact, same treatment
   `rule_propose` already gets) and Humans' fifth job (`skill_mastery`
   -> memory-only — one individual's own achievement, not a
   collective theory). Also asked (separately, docs-only, see below):
   the user's direct question about whether Nature's domain (ecology/
   forests/wildlife/geography) has any real cognition presence beyond
   the three mirrored jobs — answered "no, those stay deterministic
   Body-only" and scoped out as a genuinely NEW Nature cognition job
   design (not a mirror), filed separately.

   Coverage now: Innovation=4, Village=5, Humans=5, Nature=3,
   Reflection=3.

   **Ninth/tenth slice shipped, v1.34.11**: Innovation's fifth job
   (`era_branch` -> `world_model` observation + memory — the branch
   lean itself is a real, already-computed decision by the time the
   one narration-only LLM call fires, so this is an observation, not
   a hypothesis, same treatment `composite_entity` gets) and
   Reflection's fourth job (`musing` -> memory-only — a musing is
   Reflection's own passing voice, not a second copy of the theory
   already tracked in `reflection_notebook`). Nature stays at 3 (no
   new candidate found this pass either — every remaining unmirrored
   job belongs to a different pillar's domain).

   Coverage now: Innovation=5, Village=5, Humans=5, Nature=3,
   Reflection=4.

   **Eleventh-through-eighteenth slice shipped, v1.34.12** ("continue
   tier 0 but do many steps at once," explicit user instruction — the
   first multi-job batch instead of the usual one-or-two-per-pass
   cadence): eight more real jobs mirrored in one batch, six into
   Village and two into Humans — every candidate whose content
   genuinely fits an already-lower-coverage-relative-to-its-domain
   pillar, found by re-reading each remaining `_maybe_schedule_*`
   site's actual apply() logic rather than guessing from the name.
   Village (5 -> 11): `chronicle` (memory-only — a monthly narrative,
   not a single standing fact), `documentary` (memory-only, same
   reasoning, yearly cadence), `festival` (memory-only — an occurrence,
   not a standing fact), `religion` (`world_model` observation +
   memory — a crystallized faith is a real, high-confidence settled
   fact, same treatment `laws` gets), `faction` (`world_model`
   observation + memory — a detected, named faction is a real settled
   social fact), `guild_founding` (`world_model` observation + memory
   — a deliberately founded guild is a real settled institutional
   fact). Humans (5 -> 7): `letter` (memory-only — one individual's
   own written words), `noncore_nudge` (memory-only — one ordinary
   villager's own quiet moment, gated to only fire when the job's
   `shifts=True` branch actually taken, not the no-op case).

   Coverage now: Innovation=5, Village=11, Humans=7, Nature=3,
   Reflection=4.

   **Nineteenth-through-thirtieth slice shipped, v1.34.13** ("continue
   tier 0 with many steps at once," explicit user instruction — second
   multi-job batch): twelve more real jobs mirrored in one pass, nine
   into Village, three into Humans. Village (11 -> 20): `naming`
   (`world_model` observation — a settlement's own name is a real
   settled fact), `tradition`/`folklore`/`legend_detection` (all
   memory-only — an occurrence/tale/legend, not a single revisable
   theory), `culture_digest` (`world_model` observation — condenses
   the settlement's own accumulated culture), `institution_culture`
   (memory-only — one institution's own independently-authored
   character, mentioning it by name), `caravan` (memory-only — an
   occurrence), `town_brain` (`world_model` observation — THE central
   Village decision, mirrored the instant `town_brain.compute_
   priority` resolves deterministically, not waiting on the
   narration-only LLM call below it), `diplomacy` (memory-only —
   spans two settlements, so it lands in the one shared world-scoped
   Village pillar rather than either settlement's alone). Humans
   (7 -> 9): `personal_belief` (memory-only — one individual's own
   private theory about their life), `record` (memory-only — a
   dying villager's own written words, mirrored once at the single
   `_apply_record` call both the LLM and fallback paths already share,
   so it fires for either), `fission` (memory-only — a leader's own
   major life decision to found a new settlement, same "major life
   decision" treatment `migration_decision` already gets).

   Coverage now: Innovation=5, Village=20, Humans=9, Nature=3,
   Reflection=4.

   **Thirty-first-through-thirty-sixth slice shipped, v1.34.14**
   ("continue tier 0 with many steps at once," plus an explicit
   request to ask about `consciousness`): six more real jobs, closing
   out essentially every remaining `_schedule_llm_job` call site.
   `away_digest`/`chronicler` -> Village (memory-only — an on-demand
   recap/Q&A exchange, not a standing fact). `mind`/`rumor_interpret`
   -> Humans (memory-only — `mind` gated to a real, non-fallback
   answer only, since the fallback is just the existing template
   restated; `rumor_interpret` is one core-cast agent's own distorted
   retelling). `self_tuning_advisory` -> Reflection (`world_model`
   hypothesis + memory — Reflection's own free-standing advice about
   something it can't directly tune, genuinely uncertain by design
   until a human reviews it). `consciousness` -> Reflection
   (`world_model` hypothesis + memory, `source="consciousness"`):
   asked directly via `AskUserQuestion` (three options: mirror with
   real content hypothesis-only same as omen's exception, mirror
   occurrence-only with no content, or leave permanently unmirrored);
   explicit user answer: "Mirror into Reflection, hypothesis-only."
   Implemented with the SAME real `kind`/`detail` content the existing
   dev-console-only `consciousness_intervention_log` already carries
   (Reflection's `world_model`/`memory` are equally dev-console-depth,
   never main-UI) — the one already-public `_log` line stays exactly
   as vague ("Something in {settlement} quietly shifted") as it was
   before this change; nothing about what's shown to a player changed.

   Coverage now: Innovation=5, Village=22, Humans=11, Nature=3,
   Reflection=6.

   `sim_summary` (on-demand user-triggered stat readout in prose) was
   considered and deliberately NOT mirrored — it restates
   population/settlement/mood stats already covered by town_brain and
   other real mirrors, not a distinct piece of judgment or texture.
   Re-checked `self_tuning`'s numeric-nudge path while auditing for
   this slice: it was ALREADY mirrored (Tier 0's very first slice,
   the `if not verdict["safe"]` branch's sibling `applied` outcome) —
   the prior pass's own notes had mis-described it as still open.

   **Thirty-seventh slice shipped, v1.34.15** ("continue tier 0," a
   final audit pass): `_apply_pending_dialogue_results`' `is_llm`
   branch now mirrors into Humans' memory. Genuinely volume-safe
   unlike dialogue in general: `is_llm` can ONLY ever be the one
   dedicated voice pair (`Population.voice_pair_ids`, since v1.4.0's
   redesign collapsed LLM dialogue to a single ongoing conversation
   thread) — every other pair resolves deterministically and never
   reaches this branch, so this is bounded by construction, not by a
   new gate. Humans=11 -> 12.

   Coverage now: Innovation=5, Village=22, Humans=12, Nature=3,
   Reflection=6.

   Still fully open: observe/interpret CYCLING for any of these
   sites (they fire on their own existing cadence, not through
   `_pillar_observe_turn`/`_pillar_interpret_backpressured`),
   attention-budget arbitration for them, inbox/outbox participation.
   The one remaining real mirror candidate, deliberately NOT
   attempted: per-agent cognition (`_run_cognition`/`_apply_pending_
   cognition_results`) — every core-cast agent, once a day, is genuine
   per-agent judgment Humans' pillar currently has zero visibility
   into, but mirroring it wholesale would flood the small bounded
   `memory` FIFO with routine goal-of-the-day noise and evict
   everything else within a few days of sim time; dialogue's own
   `surfaced`/`is_llm` flags gave this same problem a natural volume
   gate for free, cognition has no equivalent today. Needs its own
   scoped design (e.g. mirror only a goal change with a genuinely
   novel LLM-authored `reason`, not every daily resolution) before
   attempting — same "needs its own explicit-direction pass" standing
   rule as the scoped-not-built Nature causal-reasoning job below.
   `pillar_chat` (already reaches its own pillar directly via `note_
   observation`) and `geography` (no LLM call) are not candidates.
   This is the practical ceiling of "mirror an existing job's output"
   — everything left is either the cognition-volume design problem
   above or a different tier of work (observe/interpret cycling,
   attention-budget arbitration, inbox/outbox participation).

   **First slice of the next tier shipped, v1.34.16** ("Start observe/
   interpret cycling, attention-budget arbitration, and inbox/outbox
   participation" — explicit user instruction). The root gap: every
   Tier 0 mirror writes DIRECTLY into `pillar.world_model`/`memory`,
   bypassing `_pillar_observe_turn` entirely — that helper only reads
   `World.emergence_log_recent()` (A22), which none of the ~50 Tier 0
   mirror sites ever populate (only the original 8 `_append_highlight`
   kinds do). So a Tier 0 mirror's content, however significant, was
   structurally invisible to its own pillar's observe/interpret cycle
   and to inter-pillar messaging — it just sat in world_model/memory
   as a direct write, never competing for bounded attention, never
   reachable by another pillar. Scoped a first slice touching all
   three named mechanisms rather than one, proven on 5-6 concrete
   sites (same "one real representative site, not a blind mechanical
   pass across all ~50" discipline every earlier B2/B3/B4 pass used):

   - **Observe/interpret cycling**: one genuinely significant Tier 0
     mirror site per pillar now ALSO calls `_append_emergence`,
     tagged for its pillar — `guild_founding` (Village, `novel_
     combination`/institution), `fission` (Humans+Village,
     `unexplained_shift`/settlement), `composite_entity` (Innovation,
     `novel_combination`), `species_variant` (Nature, `novel_
     combination`/ecology), `self_tuning_advisory` (Reflection+
     Village, `opportunity`). Each now genuinely competes for its
     pillar's bounded `working_memory` on the next `observe` turn,
     salience-ranked against everything else in the stream — not
     guaranteed visibility, a real chance at it, same as any other
     Emergence entry.
   - **Attention-budget arbitration**: `_maybe_schedule_town_brain`
     (Village's single most significant civic decision) now uses
     `_pillar_interpret_backpressured("village")` — the SAME priority-
     scaled tolerance function B3 built for the pillar's own
     `interpret` turn — instead of the flat `_settlement_job_
     backpressured()` every other settlement job shares. Reused
     directly rather than reimplemented: the function only reads/
     checks pillar state, never mutates `cycle_stage`, so it's safe
     for a sibling job to call.
   - **Inbox/outbox participation**: a new real arrow, Reflection ->
     Village (`kind="theory"`), fires whenever `self_tuning_advisory`
     forms — Reflection's own genuinely uncertain read on something it
     has no tunable governor for is exactly the kind of content worth
     handing directly to another pillar, not just leaving in the
     shared Emergence stream. Verified end-to-end: the sent message
     lands in `village_pillar.inbox`, then a real `_pillar_observe_
     turn("village")` call delivers it into `working_memory` and
     clears it from `inbox`, closing the full B4 loop with genuinely
     new content for the first time since the original three arrows
     (Nature->Village, Village->Innovation, Innovation->Village).

   Deliberately NOT attempted this pass: extending emergence-tagging/
   attention-scaling/messaging to the other ~45 Tier 0 mirror sites
   (a mechanical repeat of this same pattern, not a new design
   question — future explicit direction can ask for "more of these"
   directly); reverse-direction disagreement classification for the
   new Reflection->Village arrow (only the original Nature->Village
   site does this, a pre-existing flagged gap, not new to this pass).

   Verified: all six changes confirmed via direct production-path
   smoke tests, including one exercising the FULL B4 round-trip (send
   -> inbox -> a real `_pillar_observe_turn` call -> working_memory,
   inbox cleared). A 4000-tick LLM-disabled engine soak confirms no
   regression; `scripts/verify_native_soak.py` (2 seeds x 800 ticks)
   byte-identical — no native module touched.

   **Second slice shipped, v1.34.17** ("Extend to 45 tier 0 sites" —
   explicit user instruction, directly following v1.34.16's own
   "deliberately NOT attempted" note above). Applied the identical
   `_append_emergence` observe/interpret-cycling pattern to the
   remaining ~39 Tier 0 mirror sites across all five pillars —
   village (naming, town_brain, chronicle, documentary, chronicler,
   away_digest, tradition, folklore, legend_detection, rule_propose,
   festival, religion, institution_culture, caravan, beliefs, faction,
   institution_belief, diplomacy, laws), humans (narrative_direction,
   personal_belief, dream, memory_drift, skill_mastery, record, mind,
   noncore_nudge, letter, migration_decision, rumor_interpret,
   voice-pair dialogue), innovation (invention, ontology_proposal,
   ontology_evolution's combine/evolve branches, era_branch), nature
   (nature_mind, omen), and reflection (musing, self_tuning,
   reflection_question) — every one of these now competes for its
   pillar's bounded `working_memory` on its next `observe` turn, same
   as v1.34.16's first six sites.

   Two real bugs caught and fixed while applying this mechanically
   across so many sites at once (both via careful post-hoc
   verification, not assumed from the applying script's own "success"
   output): (1) the `beliefs` job's new-belief branch sits inside an
   `else:` block at 16-space indent — the first attempt inserted its
   `_append_emergence` call at 12 spaces, which parsed as valid Python
   but silently de-scoped the following B4 `if entry["confidence"] >=
   0.5: self._send_pillar_message(...)` block out of the `else:` it
   was meant to be inside, caught via `ast.parse()` raising `Indentation
   Error` and fixed by re-indenting to 16 spaces; (2) `rule_propose`'s
   apply() nests its actual rule-registration logic inside an `async
   def _sandbox_and_register():` closure (gated on the counterfactual-
   sandbox verdict) — the first attempt placed `_append_emergence`
   OUTSIDE that closure, at `apply()`'s own indent level, which is
   syntactically valid but references `rule` (a name that only exists
   inside the nested closure) and would raise `NameError` at runtime
   on every real firing, plus fire unconditionally regardless of the
   sandbox verdict; caught via a scripted indent-consistency scan
   (compare each inserted call's indent against its preceding
   `remember()`/`upsert_world_model()` line) and fixed by moving the
   call inside the closure, correctly gated on `verdict["safe"]`.

   Verified: an automated indent-consistency scan across every
   `_append_emergence` call site in the file (0 real mismatches
   remaining after the two fixes above — one flagged mismatch is a
   pre-existing, correctly-nested `if hub_agent is not None:` site
   from `_detect_social_hub`, unrelated to this pass); `ast.parse()`
   clean; direct production-path smoke tests for `naming`/`town_brain`
   (both confirmed writing a real `Emergence` entry) and, specifically
   targeting the two fixed bugs, `rule_propose` (confirmed firing
   end-to-end through the real `_sandbox_and_register` closure with a
   fake always-safe counterfactual verdict) and `beliefs` (confirmed
   its new-belief branch fires correctly on a pillar's real `interpret`
   turn, after an `observe` turn correctly consumes the first call per
   B2's existing cycling); `scripts/verify_native_soak.py` (2 seeds x
   800 ticks) byte-identical — no native module touched; a 4000-tick
   LLM-disabled engine soak plus a full `to_dict()`/`from_dict()`
   round-trip, both clean.

   Still fully open: attention-budget arbitration and inbox/outbox
   participation for these ~39 sites (this slice only extended
   observe/interpret cycling, matching the user's literal "extend to
   45 tier 0 sites" ask against v1.34.16's own three-mechanism list) —
   town_brain (v1.34.16) remains the only site with real attention-
   budget arbitration, and Reflection->Village (v1.34.16) remains the
   only new inbox/outbox arrow. Per-agent cognition stays the one
   deliberately-unmirrored gap (v1.34.15's own note, unchanged).

   **Third slice shipped, v1.34.18** ("Extend to other sites" —
   explicit user instruction, following directly off v1.34.17's own
   "still fully open" note above). Closes the attention-budget-
   arbitration half of that gap for all 34 remaining flat-gated
   settlement jobs, and adds three more real B4 inbox/outbox arrows:

   - **Attention-budget arbitration**: every one of the 34 sites that
     previously called the flat `_settlement_job_backpressured()` now
     calls `_pillar_interpret_backpressured(pillar)` instead, mapped
     to its owning pillar — village (chronicle, documentary,
     tradition, folklore, legend_detection, rule_proposal, festival,
     religion, culture_digest, institution_culture, caravan, faction,
     guild_founding, institution_belief, diplomacy, laws), humans
     (personal_belief, dream, memory_drift, record x2, mind-retry,
     noncore_nudge, letter, fission, migration_decision), innovation
     (invention, ontology_evolution, composite_entity), nature
     (species_variant, omen), reflection (consciousness, self_tuning,
     musing). `_maybe_interpret_rumor` was NOT touched — it already
     has its own bespoke `RUMOR_INTERPRET_BACKPRESSURE_FRACTION`
     threshold, a deliberate earlier design decision unrelated to this
     gap. Every settlement job in the codebase that mirrors into a
     pillar now genuinely shares B3's priority-scaled tolerance
     (salience + staleness + inbox pressure), not just `town_brain`.
     A pure expression swap at each site (no new lines/blocks), so
     none of the indentation/scope risk the previous slice's
     `_append_emergence` insertions carried applies here.
   - **Inbox/outbox participation**: three new arrows, chosen for
     genuinely useful cross-pillar content rather than mechanically
     covering every site — Innovation->Reflection (`discovery`) on
     `invention` (a new invention is real material for Reflection's
     own pattern detection over Innovation's Body state), Nature-
     >Innovation (`observation`) on `species_variant` (a new natural
     variant is real grounding for what Innovation might notice/build
     on next), and a second Village->Humans (`observation`) arrow on
     `faction` (a newly-named faction is a real social fact about
     specific living people). Brings the total B4 arrows to seven:
     the original three (Nature->Village, Village->Innovation,
     Innovation->Village), v1.34.16's Reflection->Village, and these
     three.

   Verified: a scripted line-by-line diff confirms every one of the
   34 backpressure swaps changed only the gate call's argument, no
   surrounding structure; `ast.parse()` clean; an indent-consistency
   scan over every `_send_pillar_message` call site (0 mismatches —
   the three new sites' indent matches their enclosing `apply()`
   body); `scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-
   identical; a 4000-tick LLM-disabled engine soak plus round-trip,
   clean; direct production-path smoke tests confirming `invention`
   and `species_variant` both fire through their real (unpatched)
   `_pillar_interpret_backpressured` gate and correctly populate the
   new arrows' outbox/inbox pairs.

   Still open: 31 of the 34 attention-scaled sites don't yet have a
   matching inbox/outbox arrow (only invention/species_variant/
   faction gained one this pass — chosen for genuine content value,
   not mechanical completeness); per-agent cognition remains the one
   deliberately-unmirrored gap.

   **Fourth slice shipped, v1.34.19** ("Continue with next milestone"
   — explicit user instruction, following directly off v1.34.18's own
   "Next Milestone" note: extend inbox/outbox participation further).
   Three more real B4 arrows, same "chosen for content value, not
   mechanical coverage" discipline as v1.34.18's three: Village->
   Reflection (`observation`) on `rule_propose` — a rule that survived
   the counterfactual sandbox and went live is exactly the kind of
   real self-modification event Reflection's meta-cognition should
   see directly, not just notice secondhand; a third Village->Humans
   (`observation`) arrow on `religion` — a crystallized faith is a
   real belief-shaping fact about specific living people; a second
   Reflection->Village (`observation`) arrow on `self_tuning` (the
   numeric-nudge job, distinct from `self_tuning_advisory`'s existing
   `theory` arrow) — a genuinely APPLIED, sandbox-validated governor
   adjustment is a settled fact about how Hearthmind changed itself,
   not a revisable theory. `omen` deliberately NOT given an arrow —
   the v1.34.9 explicit user decision to "ignore Phase G for this one
   completely" was scoped narrowly to that one `nature_pillar.
   world_model` mirror, not a blanket license to route omens through
   B4 messaging too. Brings the total B4 arrows to ten.

   Verified: `ast.parse()` clean; an indent-consistency scan over
   every `_send_pillar_message` site (0 real mismatches — the one
   flagged case is the same pre-existing, correctly-nested `beliefs`
   confidence-gated site from earlier passes); `scripts/verify_
   native_soak.py` (2 seeds x 800 ticks) byte-identical; a 4000-tick
   LLM-disabled engine soak plus round-trip, clean; direct production-
   path smoke tests for all three new arrows — `rule_propose` through
   its real sandboxed closure with a fake always-safe counterfactual
   verdict, `religion` with a forced `forms: true` result (its
   fallback always means "not yet" by design, so exercising the real
   arrow needs a genuine crystallization answer), and `self_tuning`
   with a seeded `supported` hypothesis naming a real tunable
   governor — all three confirmed populating the correct outbox/inbox
   pair with the correct `kind`.

   Still open: 28 of the 34 attention-scaled sites have no matching
   inbox/outbox arrow; per-agent cognition remains the one
   deliberately-unmirrored Tier 0 gap.

   **Fifth slice shipped, v1.34.20 — closes out attention-scaled
   inbox/outbox coverage** ("Continue and finish attention scaled
   site in one go" — explicit user instruction). Fourteen more real
   B4 arrows, one per remaining job judged to carry genuine cross-
   pillar content, closing the decision for every one of the 34
   attention-scaled sites rather than leaving the rest ambiguously
   "still open":

   - Village->Humans (`observation`): `tradition`, `folklore`,
     `festival`, `institution_belief`, `diplomacy` — each a real
     cultural/civic/social fact shaping specific living people.
   - Village->Reflection (`observation`): `legend_detection` (a
     legend crystallizing from a repeated pattern IS an instance of
     Reflection's own pattern-detection signal), `laws` (a newly-
     enacted law/custom/taboo is a real normative self-modification,
     same reasoning as `rule_propose`'s existing arrow).
   - Village->Innovation (`discovery`): `guild_founding` (a
     deliberately founded guild is an institution organized around a
     skill — real grounding for Innovation).
   - Humans->Reflection (`observation`): `personal_belief` (an
     individual's own private theory revision — real psychological
     material, monthly-bounded volume, not the daily per-agent-
     cognition problem).
   - Humans->Village (`observation`): `fission`, `migration_decision`
     — both real settlement-population-shaping facts.
   - Innovation->Village (`discovery`): `ontology_evolution` (both
     merge and evolve branches), `composite_entity` — each a genuine
     new/combined concept, same treatment `ontology_proposal`'s
     existing arrow already gets.

   Deliberately, explicitly NOT given an arrow (a real decision for
   each, not a silent omission): `chronicle`/`documentary`/`musing` —
   pure narration recapping what other arrows (or the settlement's
   own state) already carry, no new cross-pillar fact; `culture_
   digest`/`institution_culture` — reflexive self-model digests,
   already mirrored into `world_model`, nothing new for another
   pillar; `caravan` — economic exchange with no single clear-cut
   pillar recipient beyond Village itself, already mechanically
   consequential and narrated; `dream` — its own docstring states
   "Phase G/omens' ambiguity discipline applies here too," the same
   discipline that kept `omen`/`consciousness` out of B4 messaging
   in earlier passes; `memory_drift`/`record`/the `mind`-retry job/
   `noncore_nudge`/`letter` — per-agent jobs judged to carry narrower
   individual content than `personal_belief`'s got this pass, kept
   out to avoid setting a precedent of an arrow-per-per-agent-job
   that could eventually approach the same inbox-flooding risk that
   keeps per-agent cognition itself unmirrored. Total B4 arrows now
   24.

   Verified: `ast.parse()` clean; an indent-consistency scan across
   every `_send_pillar_message` call site in the file (0 real
   mismatches — the one flagged case is the same pre-existing,
   correctly-nested `beliefs` confidence-gated site from earlier
   passes); a variable-scope sanity scan (every f-string variable
   referenced in a new call also appears in its immediately-enclosing
   context — one flagged false positive, the pre-existing Nature-
   >Village arrow's `entry` variable, defined slightly outside the
   scan's fixed lookback window, confirmed fine by direct read);
   `scripts/verify_native_soak.py` (2 seeds x 800 ticks) byte-
   identical — no native module touched; a 4000-tick LLM-disabled
   engine soak plus round-trip, clean; direct production-path smoke
   tests for `tradition`, `personal_belief` (via `_run_personal_
   belief` directly), and `ontology_evolution`'s merge branch (with
   two seeded `established` concepts) — all three confirmed
   populating the correct outbox/inbox pair with the correct `kind`.

   This closes out attention-budget arbitration (all 34 sites,
   v1.34.18) and inbox/outbox coverage decisions (all 34 sites now
   have either a real arrow or a documented reason not to, v1.34.19-
   20) for the Tier 0 mirror sites named in v1.34.16's original
   scoping. Remaining genuinely open: per-agent cognition's own
   volume-safe design (unchanged since v1.34.15's flagging) — the
   practical ceiling of "extend the existing pillar mechanisms to
   more sites" as a pattern; anything past that needs a new design,
   not another mechanical pass.

   **Scoped, NOT shipped — a genuinely new Nature cognition job**
   (explicit user request, v1.34.10 pass: "Nature can have so many
   things though like ecology, forests, wildlife, geography are they
   there?"). Answer given directly: geography naming is fully
   procedural/zero-LLM (v1.3.35); forests/wildlife/climate/scars ARE
   real Body state Nature's Mind (`llm/nature_mind.py`) already reads
   — but that job is a *general seasonal belief-revision pass* (one
   theory, any subject, `season_end` cadence), never a reaction to one
   *specific* ecological event. This is the same "mirroring isn't a
   new decision point" distinction the whole Tier 0 batch has been
   careful about — a mirror duplicates an existing job's output into a
   pillar; this would be a new job with its own genuine judgment call.
   Design only, not implemented this pass:

   - **Name**: `_maybe_schedule_nature_causal_reasoning` (or similar;
     final name TBD at implementation time).
   - **Trigger**: reactive, not cadence-gated — same shape `skill_
     mastery`'s "fires the tick a `skill_mastered` life event actually
     happens" already established, not a new pattern. Candidate real,
     already-detected Body-state anomalies to react to (pick ONE for a
     first slice, per this project's own "smallest coherent milestone"
     discipline): a wildlife herd/pack crossing toward local
     extinction (`WildlifeGrid` already tracks herd/pack counts), a
     sudden multi-tile disaster-scar spike in one region within a
     short window, or forest succession stalling well past `REFOREST_
     MIN_FALLOW_WEEKS` despite favorable moisture (a real, currently
     silent anomaly — `terrain_evolution.nature_adaptation_bias`
     already reads confidence off Nature's beliefs but nothing
     currently asks "why hasn't this reclaimed yet?").
   - **Prompt**: grounds the LLM in the ONE specific anomaly (not a
     generic seasonal digest) plus Nature's existing beliefs — "Why
     might this specific thing be happening?" rather than nature_
     mind's "form any theory about the land's current state."
   - **Output**: a causal hypothesis, `status="hypothesis"` (never
     `"observation"` — genuinely uncertain by design, same discipline
     as the omen mirror), written to `nature_pillar.world_model` AND
     to `world.ontology.CausalThread` (the mechanism v1.3.41 already
     built for dispute outcomes) so the reasoning is legible via the
     existing "🔗 causal threads" UI panel, not a new one.
   - **Critical flag**: `critical=True` — this is genuine judgment
     about *why* something happened, not ambient narration; a failed/
     budget-exhausted call should defer, never fabricate a cause
     (Constitution §3/§7, same as `nature_mind` itself).
   - **Budget**: settlement-scoped-equivalent, not per-agent — an
     anomaly is world/region-scoped, so this doesn't need core-cast
     gating, but SHOULD still count against the shared daily LLM
     ceiling and backpressure gate like every other settlement job.
   - **Why not attempted this pass**: genuinely new judgment-call
     design work (which anomaly, what "why" means for a wordless land-
     intelligence, how CausalThread's dispute-shaped schema needs to
     generalize to a Nature-authored cause) — the kind of decision
     this project's standing rule says needs its own explicit-
     direction pass, not folded into a mirroring batch already in
     flight. Build only on future explicit direction naming this item.

   **Shipped, v1.34.34** ("As many slice of tier 0 as you can in this
   turn" — explicit user instruction). Picked the first named
   candidate (a wildlife herd/pack local extinction) as the smallest
   coherent first slice: new `llm/nature_causal_reasoning.py` +
   `SimulationEngine._maybe_schedule_nature_causal_reasoning`, reactive
   (not cadence-gated, same shape `skill_mastery` established), fires
   the tick `world.wildlife.summary()["predator_packs"]` crosses from
   >0 to 0 (edge-triggered via new `_nature_predator_extinction_
   flagged`, same shape `_hydrology_drought_flagged` established —
   flag is only set once the job is actually SCHEDULED, not on a
   backpressured attempt, so a busy tick retries on the next tick
   instead of silently losing the anomaly). Grounded in the specific
   anomaly plus real Nature Body state (predator pressure ratio,
   prey-scarcity flag, grazer herd count, disaster-scar count, season)
   — never settlement prosperity. `critical=True`: a failed/budget-
   exhausted call defers, never fabricates a cause. Output always
   `status="hypothesis"`, written to BOTH `nature_pillar.world_model`
   AND a new `world.ontology.CausalThread` (`settlement_id=None` —
   reuses the existing dispute-authored record shape rather than a
   parallel one, so it's legible via the existing "🔗 causal threads"
   panel with no new UI). Deliberately does NOT call `_pillar_close_
   cycle("nature")` — this job doesn't own Nature's observe/interpret
   `cycle_stage` (that's `nature_mind`'s), and force-closing it here
   could stomp a concurrently in-flight `nature_mind` call.

   Verified: a direct production-path smoke test (fake LLM client)
   confirming the full trigger/schedule/apply/round-trip path — no
   job on packs>0, correctly schedules exactly once on the falling
   edge (not re-scheduled on a repeat still-zero check), the resulting
   `world_model`/`CausalThread`/Emergence entries all populate with
   the right content and `settlement_id=None`, and the flag clears on
   recovery; a real 4000-tick LLM-disabled engine soak (async, real
   `_tick_once` loop) confirmed zero regressions through the actual
   production tick path; `scripts/verify_native_soak.py` (2 seeds x
   800 ticks) byte-identical — pure Python, no native module touched.
   Grazer/forest-succession-stall anomalies (the design note's other
   two candidates) remain open for a future slice.

**Tier 0.5 — live-diagnostic findings from a real long-running world
(filed v1.34.3, explicit user report)**, sequenced right after Tier 0
and before Tier 1: these are correctness/tuning questions about
systems Tier 0 already targets (pillar cadence) plus a few cheap-
audit-shaped findings in A9's own spirit, not new features — cheaper
and more urgent than starting Tier 1's substrate work. **Every item
below carries the user's own explicit constraint: if a change would
degrade cognition or sentience quality, don't make it** — investigate
first, only land a fix once it's confirmed genuinely free.

D1. **Reflection pillar not accumulating evidence.** A live report:
    "not yet meaningfully active despite a long simulation." Already
    partly diagnosed once before (v1.23.1, a shorter-run report): B2's
    observe/interpret cycling halves real call volume, so Reflection's
    year_end cadence needs ~2 year boundaries even in the best case
    (~70k ticks was the v1.23.1 estimate) before its first real
    interpret turn resolves — that pass's fix was "make the cold-start
    latency visible, don't change the cadence" (`Pillar.turns_
    processed` + the dev-console panel), an explicit user decision at
    the time. This new report describes a MUCH longer run still
    showing it "almost empty" — re-investigate whether cold-start
    latency alone actually explains this, or whether `_detect_
    reflection_pattern`'s own signal thresholds are separately too
    strict for a hypothesis to ever form even once interpret turns
    are firing. Fix, if any, should widen the evidence funnel
    (thresholds, what counts as a pattern) rather than force premature
    conclusions — the user's own framing ("avoiding premature
    conclusions") rules out just lowering the bar carelessly.
D2. **Nature pillar progressing much slower than the other four.**
    Same B2 halving applies (`_maybe_schedule_nature_mind`'s
    season_end cadence), but Nature's OWN gating (belief-formation
    frequency, what NATURE_EVENT_CATEGORIES counts as material) may
    independently be starving it relative to Village/Humans/
    Innovation, which don't share Nature's dependency on wildlife/
    disaster/climate events specifically. Investigate whether Nature's
    real bottleneck is the shared B2 cadence (in which case D1's fix
    helps both) or something Nature-specific.
D3. **Reduce unnecessary continuous-cadence LLM calls where event/
    milestone-driven is equivalent.** A direct precursor to Tier 5's
    Runtime Hard Rule 3 ("event-driven, not polling") but scoped to
    what's cheaply reviewable in the CURRENT architecture, not waiting
    on the full Adaptive Runtime. Audit every `_maybe_schedule_*` job's
    trigger: which ones already gate on a real state change (most do,
    via backpressure/roll chances) vs. which fire purely because a
    calendar boundary passed regardless of whether anything material
    happened since the last firing. **User's explicit constraint: any
    conversion that would degrade cognition/sentience quality is a
    hard stop, not a tradeoff to weigh.**
D4. **Justify every `deep_reasoning=True` job individually, don't
    assume all high-level cognition needs it.** v1.3.37 flagged ~20
    tasks `deep_reasoning=True` (belief revision, major life decisions,
    council deliberation, town consciousness, cultural evolution,
    invention, self-tuning) in one batch, reasoning "reallocate freed
    budget toward tasks that need genuine sentience/intelligence." That
    batch justified the CATEGORY, not each task independently. Review
    each site's actual measured latency/quality delta with vs. without
    reasoning (the recorder/review-pack tooling already captures
    `reasoning_calls_*` diagnostics for exactly this) and demote any
    task where a live measurement shows no real quality loss.
    **Same hard stop: don't demote a task if it visibly degrades
    output quality, even if it's faster.**
D5. **Rule-generation (`_maybe_schedule_rule_proposal`, `llm/rule_
    proposal.py`) occasionally produces malformed JSON.** Confirmed
    real gap: `rule_proposal` has no entry in `llm/json_schemas.py`'s
    constrained-decoding set (FT.0, v1.3.12) — it's one of the
    remaining unconstrained tasks, same class of bug FT.0 fixed for
    the eleven highest-volume tasks at the time. Give it a real JSON
    Schema (same `TriggerRule`/hook-type closed vocabulary the parser
    already validates against post-hoc) so malformed output becomes
    sampler-level near-impossible, not just retried/repaired after the
    fact.
D6. **Social scaling beyond several hundred/one thousand villagers.**
    Every agent currently has O(population) potential social surface
    (relationships/trust/debts dicts keyed by any other agent id, no
    locality partition) — realistic at a few hundred, implausible at a
    thousand+. Needs a real neighborhood/district/institution layer
    that BOUNDS an individual's implicit social awareness to people
    they'd plausibly know, with existing institutions (FAMILY/COUNCIL/
    GUILD) and factions as natural building blocks already in place.
    Real overlap with Tier 3 item 22 (A16, trade/tech/information as
    graph algorithms) and Tier 5's B10 (spatial locality partitioning)
    — this item is the SOCIAL-graph-locality counterpart to B10's
    spatial one, and probably belongs paired with it rather than
    solved twice independently.
D7. **Strengthen cumulative-culture feedback loops** (beliefs,
    inventions, traditions, institutions building on each other, not
    staying independent). A live report already confirms encouraging
    cumulative culture forming organically — this is "do more of what's
    already working," not a gap-fix. Real continuation of Tier 0's
    pillar-wiring work (more jobs feeding pillar `world_model`/memory,
    inter-pillar messages referencing prior culture) and A17
    (`world/memetics.py`'s propagation-weight primitive, still only
    wired into ontology-concept spread, not rumor/tradition/belief/
    song/technique per Tier 2 item 14).
D8. **Village-level theories' life cycle: do they ever expire, weaken,
    merge, or get accepted, or only accumulate?** `Settlement.beliefs`
    forms/revises but has no explicit "this became settled fact" or
    "this quietly faded" terminal state the way `InventedConcept` has
    `established`/`retired` (A8's evaluate+select step, v1.19.0) or
    `ReflectionEntry` has `supported`/`rejected`/`superseded`. Real
    overlap with Tier 3 item 24 (B8's un-shipped `reinforce`/
    `reinterpret`, needing per-note salience/access tracking) — a
    belief life cycle and B8's memory life cycle are close enough in
    shape that they should probably share a mechanism, not be designed
    twice.
D9. **Diagnostics should explain WHY a cognitive event happened, not
    just THAT it happened.** When a belief/invention/tradition forms,
    show which observations/memories/historical events actually fed
    that specific call's prompt — the recorder already captures
    `structured_input`/`context_snapshot` per call (v1.3.0's Context
    Influence work), so this is largely a SURFACING gap (a per-event
    "why this happened" reconstruction reading already-captured data),
    not new instrumentation. Real sibling of Tier 5's B5.4 "explain
    this tick" (execution-level why) — this is the cognition-level
    counterpart (semantic-level why); worth building with shared
    presentation conventions when both exist, not required to wait for
    B5.4 itself.
D10. **Memory consolidation over extremely long runs: still bounded
     and still preserving what matters?** `Pillar.consolidate()` (B8),
     `Agent.memories`' salience-based eviction, `Settlement.belief_
     digest`/`culture_digest`, and event-log/metrics-table retention
     are all real, already-shipped consolidation mechanisms — this
     item is a RE-VERIFICATION at much longer horizons than they were
     originally tuned/tested against (the project's longest soaks to
     date are ~20k ticks; "extremely long" live reports are pushing
     past that), not a new mechanism. Check whether any of these caps/
     thresholds need retuning at real multi-hundred-thousand-tick
     scale, and whether `Pillar.consolidate()`'s digest-of-a-digest
     folding (repeated consolidation cycles) still reads coherently
     after many rounds rather than degrading into mush.

**Tier 0.5 status (v1.34.21, "finish tier0.5 now" — explicit user
instruction).** A real decision for every D-item, same "close the
list, don't leave items ambiguously open" discipline the attention-
scaled-sites work (v1.34.17-20) just established. This environment has
no live LLM server, so D1-D4/D9's live-measurement asks couldn't be
re-run against real Ollama traffic the way they originally were —
each is closed via code-level re-audit against the SAME diagnosed
mechanisms instead, honestly scoped as re-confirmation rather than
new live data, respecting the section's own "avoid premature
conclusions" framing:

- **D5 — DONE, v1.34.21.** Root cause re-diagnosed: the original
  framing ("give it a JSON schema") would have silently and
  permanently killed `rule_propose`'s reasoning trace — it runs
  `deep_reasoning=True` since v1.3.37, and `_schedule_llm_job`'s own
  structural rule (`reasoning = deep_reasoning and task_schema is
  None`) means a schema-constrained task can never reason, exactly
  the tradeoff `beliefs`/`personal_belief` deliberately avoided by
  having their schemas REMOVED in that same pass. Applied the
  `PERSONAL_BELIEF_NUM_PREDICT_MULT` fix shape instead (new
  `RULE_PROPOSE_NUM_PREDICT_MULT=2.0`): `rule_propose` asks for a
  10-field JSON contract close to `personal_belief`'s own diagnosed
  shape (a large free-form answer sharing one flat reasoning-trace
  token budget with every simple 2-4 field reasoning job) — the same
  failure class already fixed there, not something a schema would fix
  without also silencing the reasoning the job was deliberately
  switched on for. Verified via a direct production-path smoke test
  confirming the real (unpatched) `_maybe_schedule_rule_proposal`
  passes `num_predict_mult=2.0` through to `_schedule_llm_job`.
- **D1/D2 — re-confirmed, no code change.** Re-read `_detect_
  reflection_pattern`/`_maybe_schedule_nature_mind`'s gating against
  the v1.23.1 diagnosis this report extended: the structural cold-
  start math still holds (B2's observe/interpret halving means
  Reflection's year_end cadence needs ~2 real year boundaries before
  its first interpret turn even CAN fire, before any pattern-signal
  threshold is checked) and every threshold in `_detect_reflection_
  pattern` (`PATTERN_SIGNAL_BELIEF_THRESHOLD`, `REFLECTION_ONTOLOGY_
  IMBALANCE_MIN_TOTAL`, `REFLECTION_COHERENCE_MIN_TOTAL`, `GOVERNOR_
  DRIFT_MIN_SAMPLES`) reads as a reasonable accumulation bar on
  inspection, not an obviously-too-strict one. Without a live long
  run to re-measure against, lowering any of these would be exactly
  the "premature conclusion" the report's own framing warns against —
  the existing `Pillar.turns_processed` dev-console visibility
  (v1.23.1) already makes the cold-start latency legible; no further
  change made. Nature's OWN dependency on wildlife/disaster/climate
  events (distinct from the shared B2 cadence) was re-checked and
  still looks like a real, separate, smaller contributor, unchanged
  from the original diagnosis — not independently fixed this pass.
- **D3 — audited, no gap found.** Read every `_maybe_schedule_*`
  job's trigger condition: the large majority already gate on a real
  state change (a detected candidate, a crossed pattern-signal
  threshold, a roll against a computed chance) before ever reaching
  `_schedule_llm_job`, not a bare calendar boundary. The handful that
  fire purely on cadence (`chronicle`, `documentary`, `musing`,
  `town_brain`'s narration) are deliberately ambient/narrative texture
  by design (same class this doc's own attention-scaled-sites pass
  just declined to route through B4 messaging for the same reason —
  see v1.34.20's skip list) — converting them to event-driven would
  change what they ARE (a periodic town's-eye-view versus a reaction
  to something specific), not fix a bug. No conversion made; this is
  the CURRENT-architecture audit D3 asked for, Tier 5's Runtime Hard
  Rule 3 remains the larger follow-on for when the Adaptive Runtime
  itself is built.
- **D4 — audited, no demotion made.** The recorder/review-pack
  tooling (`reasoning_calls_*` diagnostics, per-call `reasoning: bool`
  tagging) that D4 asks to read from already exists and already
  captures exactly the per-task latency/quality signal needed — but
  no live archive exists in this environment to read a real measured
  delta from, and the item's own hard stop ("don't demote a task if
  it visibly degrades output quality, even if it's faster") rules out
  demoting any of the ~20 `deep_reasoning=True` tasks on code
  inspection alone. Left as originally scoped: a live `/diagnostics`-
  driven pass, not attempted blind.
- **D6 — shipped (v1.34.22).** Explicit user directive: "at some
  number of villagers as threshold promote them to collective NPCs
  instead of single NPCs... districts, smaller towns." New `hearthmind/
  settlement/district.py`: once a settlement's individually-simulated
  non-core population crosses `DISTRICT_INDIVIDUAL_CAP=250`, the
  least-prominent excess (`Population._prominence`, ascending) is
  genuinely removed from `Population.agents`/the native `AgentStore`
  AND from every surviving agent's `Ledger` entry for them
  (relationships/trust/relationship_flags/grievances — the same
  per-survivor cleanup `_apply_deaths` established, v0.42.0, but
  without grief/memorial/inheritance since no one died) and folded
  into a `District`'s aggregate population instead. This is what
  actually bounds the social surface the original entry diagnosed — a
  collectivized person no longer has a `Ledger` entry anyone can hold.
  `DISTRICT_MAX_POPULATION=150` caps a single district before a new
  one spins up (the "smaller towns" half of the directive — growth
  reads as more named wards, e.g. "North Ward"/"Millgate", not one
  unbounded blob). Core-cast agents and any living MAYOR are never
  candidates (same "named cast stays named" boundary `core_agent_ids`
  already draws for LLM budget). A `District` is deliberately NOT an
  `Institution` or named character — no beliefs, no cognition, no LLM
  authorship — closer to `FarmGrid`/`WildlifeGrid`: ticked daily
  (`day_end`) via `tick_district` (fractional-accumulator births/
  deaths scaled by a district `avg_hunger` that exponentially smooths
  toward the settlement's individually-simulated average — a district
  has no farms/foraging of its own), plus a small per-capita passive
  materials contribution. Deliberate scope trim, recorded in `_tick_
  districts`'s own docstring: `carrying_capacity()` is NOT adjusted for
  collectivized population this pass — districts are tracked as a
  separate, additive population figure so existing individually-
  simulated population balance/tuning isn't disturbed without the
  ability to live-test the impact; folding districts into carrying
  capacity is flagged future work. Fully procedural naming (12-name
  ward pool, zero LLM cost, same precedent as `world/geography.py`).
  UI: new "Districts" main-UI stat tile. Verified: direct production-
  path smoke tests (collectivization + Ledger cleanup + materials
  contribution + starvation dissolution + core-cast protection +
  below-cap no-op, all via the real `Population`/`Settlement` classes),
  a real engine-level test (temporarily lowered thresholds, ran 3000
  real ticks through `SimulationEngine._tick_once`, confirmed districts
  form/narrate/round-trip through `to_dict`/`from_dict` via the actual
  production code path — caught and fixed one real bug in the process,
  `_append_emergence`'s `kind` argument used an invalid value
  ("observation") not in `emergence.OBSERVATION_KINDS`, corrected to
  "opportunity"/"unexplained_shift"), `scripts/verify_native_soak.py`
  (2 seeds x 800 ticks) byte-identical — no native module touched.
  Stays paired with Tier 5's B10 (spatial locality partitioning) as a
  noted relationship, not a blocker — B10 remains open, unattempted.
- **D7 — closed, no action needed.** The original live report already
  confirmed cumulative culture forming organically — this was always
  "do more of what's already working," not a gap-fix, and Tier 0's
  own pillar-wiring work (through v1.34.20) is exactly more of that.
  A17's remaining scope (unifying rumor/tradition/belief/song/
  technique onto `memetics.py`'s propagation-weight primitive) stays
  where it already was, Tier 2 item 14 — not duplicated here.
- **D8 — scoped, not built.** A real, buildable feature (add a
  terminal `status` to `Settlement.beliefs` entries — `established`/
  `faded`, the same shape `InventedConcept` already has for concepts
  and `ReflectionEntry` for hypotheses) but genuinely overlaps B8's
  own un-shipped `reinforce`/`reinterpret` (Tier 3 item 24, needs
  per-note salience/access tracking) closely enough that designing a
  belief life cycle without also touching B8's memory life cycle risks
  building the same mechanism twice, exactly the risk the original
  entry itself flagged. Left as one shared design effort for a future
  pass naming either item specifically, not built partially now.
- **D9 — substantially already closed, re-labeled rather than
  rebuilt.** Confirmed via code read: `_record_llm_debug` already
  folds every call's `structured_input` into `_last_llm_calls[name]`,
  and `full_diagnostics()` already exposes the whole `last_llm_calls`
  dict (same raw-JSON dev-console depth as `reflection_notebook`/
  `nature_pillar`) — so "which observations/memories/historical events
  fed THIS call's prompt" is already one dev-console click away for
  the most recent firing of any named job, not a gap needing new
  instrumentation, matching the item's own "largely a SURFACING gap"
  framing. The one real residual: `_last_llm_calls` is keyed by task
  NAME and overwritten each firing, so it shows the job's latest call,
  not necessarily the specific belief/invention/tradition a player is
  looking at on a timeline scrub. Closing that gap needs per-entity
  provenance tagging (a new field stored alongside each formed
  belief/concept/tradition, not a surfacing change) — real future
  work, not attempted this pass.
- **D10 — attempted at a longer horizon, honestly incomplete.** A
  fresh soak past the project's prior ~20,000-tick longest was
  attempted (target 60,000, then 30,000 ticks); per-tick cost grows
  with population (observed ~25s/5,000 ticks early, ~66s/5,000 ticks
  once population reached ~70), and this session's time budget ran out
  before either attempt finished — killed at ~10,000 ticks with no
  failure observed up to that point, but that's not a completed re-
  verification and is NOT reported as one. What IS verified this pass,
  cleanly: the standing 4,000-tick LLM-disabled soak + full `to_dict()`/
  `from_dict()` round-trip (unchanged from every other slice's own
  verification this session) shows no regression from D5's change.
  Re-running a genuine 60k+-tick structural check (do the caps hold,
  does the round-trip still match) remains open — a straightforward
  rerun, just one that needs more wall-clock budget than this pass
  had, not a design question. The CONTENT half (whether `Pillar.
  consolidate()`'s digest-of-a-digest folding still reads coherently
  after many rounds) needs a real LLM authoring real digests over real
  wall-clock time regardless — that was always going to stay open
  here, live-server-dependent per the item's own framing.
- **D11 — new, filed this pass: per-agent cognition's volume-safe
  mirroring design, scoped for a future tier rather than attempted
  now** (per the explicit instruction accompanying this Tier 0.5
  closure: "scope this problem for some other tier"). Every Tier 0
  mirror shipped through v1.34.20 covers a SETTLEMENT-scoped job
  (round-robin bounded, flat call volume regardless of population);
  per-agent cognition (`_run_cognition`/`_apply_pending_cognition_
  results`, once per core-cast member per day) is structurally
  different — mirroring it wholesale would write one entry per core-
  cast agent per day into Humans' bounded `memory`/`working_memory`
  FIFO, which would evict every other pillar signal within days of
  sim time on a full-size core cast (flagged this way as far back as
  v1.34.7 and reconfirmed at every subsequent Tier 0 pass since).
  Filed here as **Tier 3 item 30** (below) rather than left as a bare
  note: the real design question isn't "should cognition be mirrored"
  but "what's the volume gate" — candidates worth evaluating together
  rather than picked blind: (a) mirror only a goal CHANGE with a
  genuinely novel LLM-authored `reason`, not every daily resolution
  (dialogue's own `surfaced`/`is_llm` flags gave dialogue this exact
  volume gate for free; cognition has no equivalent field today); (b)
  a per-agent salience threshold reusing `_is_significant_moment` (the
  same significance gate `personal_belief`'s candidate selection
  already uses) so only a core-cast member's genuinely notable daily
  decision reaches the pillar, not the routine ones; (c) a settlement-
  level DIGEST of the day's cognition resolutions (one mirror write
  per settlement per day summarizing N agents' choices) instead of
  one write per agent, trading per-agent specificity for the flat-
  volume shape every other Tier 0 mirror already has. Not designed
  further here — a future explicit pass naming this item should pick
  between (a)/(b)/(c) (or a combination) before writing code, the same
  "design before build" discipline B6/B7's own open decisions got
  before they shipped.

  **Shipped, v1.34.34** ("As many slice of tier 0 as you can in this
  turn" — explicit user instruction, read as the "future explicit
  pass naming this item" the design note above called for). Picked
  option (a): `SimulationEngine._apply_pending_cognition_results`
  mirrors a core-cast agent's goal CHANGE into `humans_pillar.memory`
  + an `unexplained_shift`/`cognition` Emergence entry. The volume
  gate falls out for free from two already-true facts rather than a
  new mechanism: every entry reaching this loop is ALREADY a genuine
  LLM-authored result (a fallback never queues into `_pending_goal_
  results` — `_run_cognition`'s `used_fallback` branch defers instead,
  see `_schedule_llm_job`'s `critical` docstring), and the previous
  goal is captured before applying the new one, so only an actual
  CHANGE (not a same-goal reaffirmation) mirrors — a core-cast member
  reconsiders on most due cognition calls but doesn't always act
  differently, so this fires far less than once/agent/day, unlike a
  blind per-call mirror. The forced-survival-override branch (hunger/
  energy past threshold overrides the LLM's raw goal) still mirrors —
  the FORCED goal is what actually happened, using the LLM's own
  reason text, same as everywhere else in the codebase this override
  already applies.

  Verified: a direct production-path smoke test against the real
  `_apply_pending_cognition_results` (goal-change mirrors + emits an
  Emergence entry; no-change goal mirrors nothing; a forced survival
  override still mirrors using the real reason text); `scripts/
  verify_native_soak.py` (2 seeds x 800 ticks) byte-identical — pure
  Python, no native module or persisted schema touched.

**Tier 1 — substrate items other systems will lean on**
1. **A9** — feedback-loop audit. **Done, v1.34.0** — see its full
   entry below for findings/fixes/follow-ups.
2. **A11** — **shipped, v1.34.23** (groundwater + erosion feeding back
   into `Tile.elevation`) — see its own entry below for detail. Was
   blocking A3's rivers-re-carve item; that item itself remains open.
3. **A1** — **third field shipped, v1.34.35** (`pollution`, joining
   `population_density`/`disease_pressure`). Nine of the other ten
   named fields (fertility/nutrients/scent/traffic/heat/cultural-
   influence/ownership/beauty/noise) remain unbuilt, plus migrating
   `mining_scars`/`disaster_scars`/the climate grid onto `FieldGrid`
   properly instead of staying separate stores — see the item's own
   entry below.
4. **A2** — **third real consumer shipped, v1.34.35** (`pollution`'s
   `diffuse` call, joining `disease_pressure`'s). `reaction_diffuse`/
   `cellular_step` still have no second consumer — see the item's own
   entry below.

**Tier 1.5 — The Living Map (filed v1.34.4, full detail docs/VISION-
2026-07-24-LIVINGMAP.md, explicit user vision)**, sequenced after
Tier 1's substrate work (specifically A11's mutable-elevation item,
which several of these depend on) and before Tier 2's mechanism gaps:
the map should let a player read the world's history off it directly
— today's rendering leans closer to "static procgen map with agents
on top" than the living-landscape target. Cross-referenced against
what's already real rather than treated as greenfield — a fair amount
partially exists (the four scar-shaped overlays, the "🗺️ fields"
toggle, layout/architecture/dialect grammar, ERA-styled cartography,
forest reclaim). Real gaps, roughly by leverage:
- **M2/M8** — `Tile.elevation` staying immutable is the single
  biggest blocker: real erosion, flooding-reshapes-the-land, quarry
  scars as actual terrain change (not a flat color tint), and rivers
  re-carving their course (A3's own remaining half) are ALL gated on
  this one item, already named in A11's own entry above.
- **M6/M7** — **legend slice shipped, v1.34.30**: the "🗺️ fields"
  toggle (moisture/soil fertility/population density/disease pressure)
  had no legend at all — a color alone never said whether it was
  showing 0.3 or 0.7, or even which direction was "good." New
  `#field-legend` (mirrors each mode's real color mapping exactly:
  gradient + plain-language low/high labels, e.g. "depleted -> rich"
  for soil fertility, not raw axis names), shown only while a field
  overlay is active. Positioned to stack above the minimap (bottom-
  right) after a real collision was caught in verification — the
  natural bottom-left spot is already `#consequences-strip`'s home.
  This is the "legends" quarter of the doc's four-part ask
  (gradients/hotspots/thresholds/legends).
  **Gradients + hotspots shipped, v1.34.31**: `FIELD_COLOR_STOPS`
  replaces each mode's flat single-hue alpha with a real 3-stop RGB
  interpolated gradient (moisture: tan -> green -> blue; soil
  fertility: red -> tan -> green around the real 0.5 midpoint;
  population density/disease pressure: pale -> orange -> red heat
  ramps) — the legend bar is generated live from the SAME stops array
  the overlay itself paints from, so the two can never drift apart.
  Each mode's peak cell/region (soil fertility tracks the extreme
  furthest from 0.5, not the raw max, since a notable LOW is just as
  real as a notable high) gets a genuine hotspot marker (a white ring)
  on the map plus a "hotspot at (x, y)" legend line, floored at
  `FIELD_HOTSPOT_MIN_VALUE` so an all-empty field doesn't get a
  meaningless marker.
  **Thresholds shipped, v1.34.32**: audited all four field modes
  against their real backend constants before drawing anything —
  `farms.SOIL_FERTILITY_MIN` is an asymptotic floor, not a decision
  line; `MIGRANT_DENSITY_DAMPENING`/`OUTBREAK_DISEASE_PRESSURE_WEIGHT`
  are both continuous multipliers with no qualitative cutoff in their
  0..1 domain. Moisture is the one mode with a genuine two-sided
  mechanical threshold — `hydrology.WETLAND_FORM_MOISTURE_THRESHOLD`
  (0.75) — a tile sustained above this line can convert to a real
  different biome (M4's `tick_wetlands`, already shipped). New
  `drawFieldContour` traces a real isoline (edge-crossing detection
  against each dense-grid cell's right/bottom neighbor, not full
  marching-squares — sufficient at this map's resolution) only in
  moisture mode; the legend gains a matching "wetland-forming
  threshold (0.75)" line, shown only for moisture. Drawing a contour
  on the other three modes would be exactly the "raw tint a player has
  to guess the meaning of" the vision doc's own worked examples warn
  against — deliberately not done.
  **Responsive canvas shipped, v1.34.33 — closes M6/M7.** The drawing
  BUFFER (`canvas.width`/`.height`, world pixels = tiles * `CELL`)
  stays the map's one coordinate system, untouched — only the CSS
  DISPLAY size now tracks the actual viewport via new `resizeCanvas
  Display()`, bounded `[0.3x, 1.5x]` of the buffer so a huge map never
  forces page scroll and a small map never sits as a tiny fixed block.
  Wired at every `drawStaticTerrain()` call (buffer-size changes) and a
  debounced `window.resize` listener. Mouse-event math (`wheel`/`mouse
  move` pan/`click`) now derives a buffer/display scale factor via new
  `canvasEventPoint()`, the same pattern `relCanvas`'s hover handler
  already established (`scale = relCanvas.width / rect.width`) — hit
  testing, zoom-around-cursor, and drag-pan all stay pixel-accurate
  even when the two sizes diverge. `#map-panel`'s `flex: 0 0 auto`
  auto-tracks the new CSS canvas size with no separate panel-sizing
  code needed; the minimap/season-vignette overlays needed no change
  (already fraction- or `inset`-based, not buffer-pixel-based).
- **M1/M9** — **old-road-beds slice shipped, v1.34.26** (extends the
  scar-shaped-dict pattern, already proven 4x: mining/disaster/ritual/
  ruin, to a 5th axis). Field boundaries and a labeled "environmental
  stress"/degradation reading remain unbuilt — same mechanism, future
  slices, not attempted this pass.
- **M4** — **shipped, v1.34.27-.28** (migration-trail slice: `World.
  migration_trails`, gained from GRAZER movement, a real feedback loop
  via move-candidate weighting rather than a downstream consumer;
  wetland/marsh slice, v1.34.28: new `Biome.WETLAND`, `world/hydrology.
  py`'s `tick_wetlands` — a GRASSLAND tile sustained near-saturated for
  `WETLAND_FORM_MONTHS_REQUIRED` months converts, and reverts once it
  dries out; real consequence via existing biome-gated systems, WETLAND
  is in neither `FARMABLE_BIOMES` nor `WALKABLE_BIOMES`, no bespoke
  consumer needed). M4 fully closed.
- **M10** — **direct look taken + shipped, v1.34.29**: a real
  Playwright screenshot of the base map (default 64x64 world, every
  overlay off) at the old `CELL=8` showed the actual problem — a fixed
  512x512px canvas element, a small corner of any real browser window,
  contradicting CLAUDE.md's own standing Observatory UI direction
  ("the map is the primary interface, read at a glance"). Fixed the
  safe, self-contained lever available without touching the zoom/pan
  coordinate system: `CELL` raised 8 -> 12 (every draw call and every
  mouse-position calculation already derives from this one constant).
  Verified via screenshot (map now visibly dominates the layout) and a
  real Playwright click test (tile (19,19) correctly resolved, inspector
  opened with real content) confirming click/hover/zoom/minimap math
  still lines up. A full responsive canvas (resize-to-viewport) remains
  the rest of M6/M7's larger redesign, not attempted here.
- **M11/M12** — folded into the standing-discipline items (A23-A25
  above) as an ongoing completeness bar, not a one-shot task; also now
  recorded in CLAUDE.md's Observatory UI direction section directly.

**Tier 2 — real mechanism gaps, each self-contained**
5. **A3** — **shipped, v1.34.25** (rivers re-carving via erosion) —
   see the item's own entry below for detail.
6. **A4** — convert remaining scripted subsystems (agriculture,
   infrastructure, economy, information) to continuous field/threshold
   updates instead of discrete "fires."
7. **A15** — wildlife/animal genetics (humans-only today); bridge to
   `world.wildlife.SpeciesVariant`, which stays purely descriptive.
8. **A14** — the other five named organism-biology subsystems (stress,
   reproduction, development, injury-recovery, sleep) beyond immune
   response.
9. **A18** — a real authoring system for new composite reactions (today
   exactly one hand-authored `CompositeReaction` exists); the doc's own
   "raid" example scoped down to relationship-rupture, a real combat/
   raid mechanic remains unbuilt.
10. **A19** — the six remaining named history axes (traffic, pollution,
    fertility, ownership, construction, ecology) beyond mining/
    disaster/ritual/ruin.
11. **A21** — legend feedback into tradition/religion/institution
    formation; using a formed legend as grounding context in other
    prompts; unifying with folklore.
12. **A20** — a second real multi-scale field beyond `population_
    density`; "culture aggregates settlements' information-ecosystems."
13. **A13** — a real automatic reactor (today: query-only, nothing
    actually fires a reaction and mutates a standing building's
    material after the fact).
14. **A17** — unify rumor/tradition/belief/song/technique onto
    `memetics.py`'s propagation-weight primitive; a shared mutate/
    decay/compete step; a real fitness-vs-truth axis for rumors.
15. **B5** — Innovation's affordance/reaction query (A5/A6/A13) is now
    actually buildable — those three Stage IV items shipped after B5's
    own first version deliberately deferred "until the substrate
    exists to query." Revisit: let Innovation's propose-step read
    `discover_reactions`/`discover_combinations` for real, not just
    `pattern_signal_counts` pressure.
16. **C4** — the runtime-auditor half: nothing today automatically
    retires persistent state with no reader ("reject state no system
    observes"). Today's C4 is only the review-time human discipline;
    the spec explicitly also wants a runtime check.

**Tier 3 — deepen an already-real mechanism**
17. **A5/A6** — per-instance `Entity.affordances`/`Entity.properties`
    (today: class-level `dict[BuildingKind, ...]` only); the validate-
    step half of A6 (re-checking a PROPOSED concept against this layer,
    not just grounding the generate-step).
18. **A7** — a real recursive rewrite/production system in each domain
    (today: layout is a scoring bias, architecture a fixed three-slot
    production, dialect one-rule-per-call); ritual/recipe-structure
    grammar (the spec's fourth named domain, deliberately left LLM-
    authored so far); rules themselves becoming LLM-proposable.
19. **A8** — sandbox forward-simulation (`simulation/sandbox.py`) as a
    fitness input; grammar-based mutation (A7) as an alternate generate
    path alongside the existing LLM propose/evolve/merge.
20. **A10** — migration, competition, decomposition, pollination (→
    vegetation), habitat formation; folding the food web onto A1's
    field substrate as one coupled system.
21. **A12** — per-instance `Entity.material` (today: class-level, one
    material per `BuildingKind`).
22. **A16** — trade-as-network-flow, tech-as-DAG, information-
    propagation-as-graph-algorithm (today: only centrality is shipped).
23. **B4** — reverse-direction disagreement classification: only the
    Nature→Village message site checks whether the receiver already
    disagrees; Village→Innovation/Innovation→Village default to flat
    `theory`/`discovery` tags without that check.
24. **B8** — `reinforce`/`reinterpret` (today: `consolidate`/forget
    only) — needs per-note salience/access tracking across all five
    pillars.
25. **C2** — most of the spec's named pillar-emitted intentions (invent
    tech, set custom, change law, reorganize institution, shift land
    use, domesticate, build, propose experiment) still aren't pillar-
    emitted at all — they're separate deterministic/LLM mechanics
    outside the five-pillar refactor's current reach. Real progress
    here mostly waits on Tier 0's bigger refactor.
26. **C3** — "pillars may initiate contact" (today: player-initiated
    only, via `/ask/{pillar}`).

**Tier 4 — standing discipline, re-audit periodically rather than
"finish" once**
27. **A23** — composability-over-content is a review-time rule, not a
    ships-once feature: keep enforcing it on every new subsystem.
28. **A24** — physical-consistency validation staying inviolable as
    Part B/C gain power — re-confirm whenever a pillar gains a new
    intention-writing capability.
29. **A25** — periodically re-audit LLM call sites: has anything that
    used to need genuine judgment become mechanically deterministic
    (a candidate for A7's grammars or A1's fields) since it was last
    checked?
30. **Per-agent cognition's volume-safe mirroring design** (filed
    v1.34.21, Tier 0.5 item D11 — "scope this problem for some other
    tier," explicit user instruction). Every Tier 0 settlement-level
    mirror (through v1.34.20) is round-robin/flat-volume by
    construction; per-agent cognition (`_run_cognition`/`_apply_
    pending_cognition_results`) is once-per-core-cast-member-per-day —
    mirroring it wholesale would flood a pillar's bounded `memory`/
    `working_memory` FIFO within days of sim time. Real design
    question: what's the volume gate, not whether to mirror. Three
    candidates worth evaluating together before writing code (see
    Tier 0.5's D11 entry above for detail): (a) mirror only a goal
    CHANGE with a genuinely novel reason, dialogue's own `surfaced`/
    `is_llm` shape; (b) a per-agent significance threshold reusing
    `_is_significant_moment`; (c) one settlement-level daily digest of
    N agents' resolutions instead of one write per agent. This is the
    practical ceiling of "extend the existing pillar mirror pattern" —
    everything else in Tier 0 was closable by extending that pattern
    directly; this item needs a new one first.

**Tier 5 — HearthBench & the Adaptive Runtime (filed v1.34.2, a
separate two-part program, sequenced strictly AFTER Tiers 0-4)**
31. **The whole checklist in `docs/HEARTHBENCH-RUNTIME-2026-07-23.md`**
    — folded in per explicit user request, ordered to run only once
    every item above is done. Two independent programs sharing one
    telemetry seam (Part C): **HearthBench** (Part A, a standalone
    model-selection benchmark — mostly buildable on existing
    foundations: `build_llm_client`, `eval_harness.py`, `recorder.py`,
    `quality_labels.py`) and **the Adaptive Runtime** (Part B, an
    OS-like execution layer deciding when/where/how work runs — nearly
    all greenfield; today everything still runs every tick because
    time passed, which the doc's own Hard Rule 3 forbids). See that
    doc's own "SEQUENCE" section for the two tracks' internal step
    ordering (Runtime: replay-hash test first, then B0/B1 task
    declaration + B5.4 "explain this tick," then B5 profiling, B9/B3
    timescales+dirty-tracking, B2/B10/B4 budgets+locality+dormancy,
    B11/B12 memory+history, B15.5/B15.3/B15.6 reference-mode+
    escalation-ladder+profile-recording, then B6-B8/B13 adaptive
    tuning last. HearthBench: A1/A2 skeleton+adapter, A3.1 fixture
    export, A4.1+A5.7/A5.8 deterministic scorers, A13 CI regression
    guard, A7/A8 metrics+diagnostics, A9/A10/A12/C5 reports+score+UI+
    passport, A4.2/A4.3 judge+human calibration, A5.11 world-level run
    last). The two tracks run in parallel with each other, both
    starting only after Tier 4.

    **Why sequenced last, not folded into Tiers 0-4's own ordering**:
    this is infrastructure FOR building/measuring Hearthmind, not a
    Hearthmind feature itself — every earlier tier item changes what
    the simulation IS; this changes how it's run and how a model
    choice for it gets evaluated. Building it before the Body/Mind/
    Seam work above stabilizes would mean re-profiling and re-
    benchmarking against a moving target repeatedly. `B0`'s prime
    invariant ("gameplay never makes scheduling decisions") and the
    Tier 0 pillar refactor's own eventual per-pillar cadence work are
    also natural neighbors (`B9` hierarchical timescales overlaps real
    territory with B2/B3's attention-scheduler cadences already
    shipped) — worth a fresh look at that overlap when Tier 5 actually
    starts, not assumed away here.

---

## Full per-item detail

Copied close to verbatim from `docs/MASTERCHECKLIST-2026-07-22.md` so
this document stays a faithful snapshot, not a paraphrase that could
drift from the source of truth. Consult that doc directly for full
context/rationale on any item — this is the "what's left" extract.

### A1 — Continuous environmental fields
**Third field shipped (v1.34.35): `pollution`.** `population_density`
and `disease_pressure` were the only two real fields before; nine of
the remaining ten named (fertility, nutrients, scent, traffic, heat,
cultural-influence, ownership, beauty, noise — moisture is really
A11's, already shipped there) are still unbuilt. `terrain_activity`/
`disaster_scars` and the climate grid remain separate stores, not
migrated onto `FieldGrid` (`mining_scars` is now a real `pollution`
input, see below, though the store itself stays separate). `pollution`
sources from two already-real Body-state producers — standing
FACTORY/POWER_PLANT/OIL_RIG buildings (`World.POLLUTION_SOURCE_
KINDS`) and `World.mining_scars` intensity, weighted so a standing
factory dominates over a scarred hillside alone — then spreads via
`ca_operators.diffuse`, same shape `disease_pressure` already
established. Real consumer: `economy.farms.FarmGrid.plant()` gained a
`pollution` yield-penalty factor (bounded floor
`FARM_POLLUTION_YIELD_MIN_FACTOR=0.6`, same shape `moisture`'s yield
factor already has) — "industry chokes the fields nearby" is now a
mechanical fact. Also given a real map overlay (5th "🗺️ fields" mode,
`interface/static/app.js`) in the same batch, per the standing
workflow rule that a new feature gets UI surfacing in the batch it
lands in.

### A2 — CA / diffusion / reaction-diffusion operators
**Third real consumer shipped (v1.34.35).** `diffuse`/`reaction_
diffuse`/`cellular_step` already had two consumers (forest succession
since v1.14.0; `disease_pressure` since v1.34.24); `FieldGrid.step_
pollution` (A1, above) is the third, spreading a raw per-region
pollution census (industrial buildings + mining scars) into
neighboring regions — real industrial impact isn't confined to the
exact region a factory's tile falls in. `reaction_diffuse`/`cellular_
step` still have no second consumer; the doc's other named example
(fire spread) remains open.

### A3 — Procedural generation as continuous runtime
**Rivers re-carving shipped (v1.34.25).** `hydrology.recarve_rivers`
re-walks each of `World.river_sources` (captured once at genesis via
the new `river_sources_used`) by the same steepest-descent rule
`generate_rivers` used, but against CURRENT elevation — real
consequence of A11's erosion (v1.34.23) actually changing `Tile.
elevation` over time. Monthly cadence (same as climate drift). A tile
no longer on the new path reverts to its elevation-derived biome
(`classify_with_bias`); a newly-visited tile becomes `Biome.RIVER`.
Developed tiles (standing building/vehicle/farm) are protected in
both directions — never carved through, never reverted out from under
a structure. New `World.river_tiles`/`river_sources` persisted state,
`river_tiles_shifted_total` counter, `river_recarved` event category.
Settlements/cultures still evolve via LLM, not deterministic procgen
(arguably correct per the Body/Mind split, flagged as an open
question rather than a clear gap) — that half remains open.

### A4 — Continuous systems vs. scripted events
Agriculture, infrastructure, economy, and information subsystems are
still partly event-driven rather than continuous field/threshold
updates. Economy → resource/price fields that flow; agriculture →
fertility/moisture field consumption; information → propagation on the
social graph (A17) are all still unconverted.

### A5/A6 — Affordances
`Entity.properties`/per-instance `Entity.affordances` (today: class-
level `dict[BuildingKind, frozenset[str]]` only). A6's validate-step
half (re-checking a PROPOSED concept against the affordance layer,
distinct from the shipped generate-step grounding) not attempted.

### A7 — Grammar-based procedural systems
None of the three shipped domains is a full graph/shape grammar
(layout = scoring bias, architecture = fixed three-slot production,
dialect = one-rule-per-call, not recursive). Ritual/recipe-structure
grammar (the spec's fourth domain) deliberately left LLM-authored.
Rules being themselves LLM-proposable not attempted.

### A8 — Evolutionary Innovation loop
Sandbox forward-simulation as a fitness input; grammar-based mutation
(A7) as an alternate *generate* path alongside the existing LLM
propose/evolve/merge — both open.

### A9 — Producer/consumer feedback loops
**CLOSED, v1.34.0-v1.34.2.** 15 named state stores checked; most
already genuinely closed loops. Three real gaps found and fixed:

- `World.mining_scars`/`disaster_scars` (v1.34.0) now bias `Population.
  _choose_build_site` away from badly scarred ground (new `MINING_
  SCAR_SITE_PENALTY_SCALE`/`DISASTER_SCAR_SITE_PENALTY_SCALE`, `world/
  terrain_evolution.py`).
- `world/spatial_memory.py`'s `location_character()` (v1.34.1): split
  into `location_character_from_dicts(...)` (the real logic) + a thin
  `World`-scoped wrapper; `_choose_build_site` now reads its mining/
  disaster/ruin scoring from ONE call to the former instead of three
  duplicate `.get()` lookups. The `World`-scoped wrapper itself still
  has zero callers (nothing with `World` in scope needs it yet) — a
  future dialogue/cognition/NPC-inspector location-flavor consumer
  remains open, not attempted (a separate, smaller finding, not
  re-opened by the "closed" verdict above — the read-side duplication
  itself IS fixed).
- `llm/ontology.py`'s `PRESSURE_SIGNAL_LABELS["materials_bottleneck"]`
  (v1.34.2): had a label with no writer anywhere. `_detect_settlement_
  bottlenecks`'s existing edge-trigger now increments it, same shape
  as `dispute_feud`/`nature_adaptation`'s existing sites.

Two of the original four "recorded, not fixed" findings were
CORRECTED on re-examination (v1.34.2), not fixed — they were never
real A9 violations: `world/architecture_grammar.py`'s per-building
descriptor and `World.causal_threads` are both deliberately UI-facing
flavor content by their own design docs (same category as dream text
or chronicle narration — never required to feed back mechanically).
`Agent.genome` is already a genuine closed loop (birth -> `Agent.
traits`, read everywhere trait behavior matters) — "never revised
post-conception" is correct biology, not a gap; `hardened_traits`
already covers "life events permanently reshape behavior" at the
phenotype layer, the right layer for that mechanism.

`Settlement.legends`'s write-only status is real but was ALREADY
tracked as its own separate finding under A21 above ("legend feedback
into tradition/institution formation... remains open") before this
audit — not a new A9 item, and not something A9's closure claims to
have resolved.

Also surfaced (unrelated finding, not an A9 item): `scripts/verify_
native_soak.py` shows a pre-existing MISMATCH at tick 1055, confirmed
via `git stash` to predate this pass — a real open native/fallback
divergence needing its own diagnostic pass.

### A10 — Ecology / food webs
Migration, competition, decomposition, pollination (→ vegetation), and
habitat formation (reads fields, writes carrying capacity) all remain
unbuilt beyond the shipped predator-prey feedback and nutrient
cycling. Folding the whole food web onto A1's field substrate as one
coupled system is real follow-up work.

### A11 — Continuous hydrology
**Shipped, second slice (v1.34.23).** Groundwater and erosion, the two
pieces flagged unbuilt above, both landed in `world/hydrology_field.
py`. Groundwater: a per-tile subsurface reservoir distinct from
surface moisture — wet land infiltrates a fraction into it each week,
dry land seeps a fraction back out (a real base-flow/spring effect,
land that was recently wet resists drying faster than land that never
was), with a small constant percolation loss so it settles to a real
equilibrium rather than ratcheting upward. Erosion: `Tile.elevation`
turned out to already be storage-layer mutable on both the native
`TerrainGrid` and the Python fallback since v0.74.1 (`TerrainGrid.
_set_tile` already accepted and stored any elevation value) — nothing
needed to change there; `tick_erosion` is simply the first real WRITER
of a new elevation value, reusing `tick_hydrology`'s own steepest-
descent neighbor search: a genuinely wet (flow-carrying, not just
damp) tile moves a small, capped, mass-conserving fraction of its
elevation excess to its lowest neighbor, re-deriving biome via
`classify_with_bias` whenever a tile's elevation crosses a real
threshold (the one real coherence hazard — nothing else in the
codebase reads raw `.elevation`, every consumer keys off `.biome`).
Deliberately out of scope: siltation into standing water (erosion
never transfers onto a pinned water/RIVER tile). Weekly cadence,
called immediately after `tick_hydrology` (`World._tick_disasters`),
same R7 pure-Python-first deviation `hydrology_field.py`'s own
docstring already justified. New `terrain_eroded` event category (adds
to `TERRAIN_CHANGING_CATEGORIES` so the map resyncs), a `World.tiles_
eroded_total` counter, and `summary()`'s `hydrology` block gained
`avg_groundwater`/`tiles_eroded_recorded`. UI: "Soil moisture" stat
tile extended with a groundwater reading, new "Erosion" stat tile.
Verified: direct smoke tests (terrain-gradient smoothing + exact mass
conservation over 400 simulated weeks, groundwater/moisture bounds
under 200 alternating wet/dry weeks, flat-terrain zero-erosion edge
case, `to_dict`/`from_dict` round-trip, legacy-snapshot groundwater
backfill); a real 3000-tick engine run (LLM disabled) through
`SimulationEngine._tick_once` confirmed both mechanisms fire through
the actual production path (28 tiles eroded) with a clean `World`-
level round-trip; `scripts/verify_native_soak.py` (2 seeds x 800
ticks) byte-identical — erosion's elevation writes go through the
exact same `TerrainGrid` storage API every other terrain mutator
already uses, so this re-confirms that path rather than introducing
new native-parity risk. This closes A11, the roadmap's own "highest-
leverage remaining item" — A3's river-re-carving and several Tier 1.5
Living Map items (M2/M8) that were blocked on mutable elevation are
now unblocked, not yet attempted.

### A12 — Material science
Per-instance `Entity.material` (today: one material per `BuildingKind`
at the class level, not per physical instance).

### A13 — Chemistry / reaction system
A real automatic reactor — the spec's literal `ReactionRule(reactants,
conditions, products, rate)` with automatic tick-loop firing that
mutates a standing building's actual material — remains unbuilt; today
ships the query half only (`discover_reactions`, read-only).

### A14 — Layered organism biology
Stress, reproduction, development, injury-recovery, and sleep (five of
the spec's six named subsystems) remain open — only immune response
(the doc's own worked example) shipped. A genetic contribution to
baseline `immune_strength` (today: nutrition/rest only) is a flagged
future connection to A15.

### A15 — Genetic inheritance
Wildlife/animal genetics (scoped to humans this pass). `world.wildlife.
SpeciesVariant` stays descriptive-only, not wired to real heritable
genes — deferred specifically to avoid `AnimalHerd`'s native-index
parity risk.

### A16 — Graph algorithms
Trade-as-network-flow, tech-as-DAG, and information-propagation-as-
graph-algorithm (A17) are unbuilt — only weighted-degree centrality is
shipped (plus community detection, already present under the `FACTION`
name).

### A17 — Information ecosystem
Rumor/tradition/belief/song/technique each stay on their own
independent, mature, deliberately-untouched mechanisms — only ontology-
concept spread uses the new `memetics.py` propagation weighting.
Folding them onto one shared mutate/decay/compete step, plus a real
fitness-vs-truth axis for rumors (false beliefs propagate if fit, not
suppressed for being false), is real follow-up work.

### A18 — Composable event reactions
Only one hand-authored `CompositeReaction` exists — no general
authoring system yet (a village can't propose its own combinations the
way `TriggerRule` is LLM-authored). The doc's own "raid" example is
scoped down to a relationship-rupture consequence; a real combat/raid
mechanic remains unbuilt.

### A19 — Persistent spatial memory
Only 3 of the spec's 9 named axes are unified (mining/disaster/ritual,
plus ruin as a 4th added later) — traffic/pollution/fertility/
ownership/construction/ecology remain separate or unbuilt. `FarmGrid.
soil_fertility`/the A1 field substrate are a different shape
(continuous fields vs. sparse per-event dicts) and folding them in is
real follow-up work.

### A20 — Multi-scale simulation
A brand-new second field beyond `population_density`, and "culture
aggregates settlements' information-ecosystems" (the spec's other
named example), remain open.

### A21 — Temporal compression
Legend → tradition/religion/institution feedback; using a formed
legend as "already legendary" grounding context in other prompts
(chronicle/dialogue/folklore); any unification with folklore itself —
all open, see CHANGELOG.md's [1.28.0] entry for exactly what shipped.

### A22 — Emergence API
Not literally "every deterministic subsystem" produces observations
yet (today: highlights, reflection hypotheses, ontology promotion, a
materials-bottleneck detector, the social-hub detector) — more
producers are a standing, ongoing follow-up as new subsystems ship.

### A23/A24/A25 — Standing discipline
Not "features" to finish — periodic re-audit items. A23: keep
rejecting isolated new mechanics at review. A24: re-confirm physical-
consistency validation stays inviolable as Part B/C gain power. A25:
periodically re-check whether an LLM call site has become a candidate
for a grammar/field/propagation mechanism instead.

---

## Part B — The Cognitive Mind (LLM_Pillars.md, five pillars)

Every item B1-B9 is marked "shipped"/"shipped a first version" in
`docs/MASTERCHECKLIST-2026-07-22.md` — genuinely real, not stubs — but
nearly every one carries the same asterisk: proven against exactly
ONE representative production call site per pillar, not the full
domain the spec names. See Tier 0 above for the one item that matters
more than all the others combined.

### B1 — The Pillar abstraction
Real `consolidate`/`forget`/`reinforce`/`reinterpret` memory semantics
(today: a capped FIFO, `consolidate` folds old notes but doesn't
selectively reinforce/reinterpret by salience — that's B8's own listed
gap). The full "refactor ~55 scattered jobs into acts of these five"
— **the single largest open item in Part B**, see Tier 0.

### B2 — The continuous cognitive cycle
Structurally complete for the one job per pillar it covers; the open
half is the same as B1's — extending observe→interpret→remember→plan→
act→reflect cycling to every LLM call site, not just five.

### B3 — The Attention Scheduler
`message_count`/`player_focus` inputs to `compute_priority()` both
still read a hardcoded 0 — real, ready inputs (B4's message bus and
C3's player-chat both now exist and could feed them) that nothing
populates yet. Round-robin arbitration is still trivial with one job
per pillar; real arbitration needs Tier 0's broader refactor first.

### B4 — Inter-pillar consciousness bus
Reverse-direction disagreement classification (does the RECEIVER
already hold a conflicting theory) is wired only at the Nature→Village
send site; Village→Innovation and Innovation→Village default to flat
`theory`/`discovery` tags without that check — see Tier 3.

### B5 — Innovation as conscious scientist
Evolve/merge untouched by this pass (only propose gained the
hypothesis/outcome loop). The real affordance/reaction query this item
always wanted was explicitly deferred "until Stage IV's substrate
exists" — Stage IV (A5/A6/A13) has since shipped first slices, so this
is now genuinely actionable, not blocked — see Tier 2 item 15.

### B6 — Reflection as meta-scientist
"Track whether its advice worked" for the advisory-proposal path was
deliberately not attempted — there's no mechanical effect to measure
an outcome against for free-text advice (unlike a governor nudge,
which has a real before/after). The human's own accept/reject marking
IS the tracked outcome by design, not a gap needing more automation.

### B7 — Humans collective consciousness
Scoped to making the collective mind AWARE of voice-pair rotation —
the deeper "individual acts locally, collective sets the mood/
direction" architecture is real but, like B1-B3, only wired at this
one site. Broader coverage needs Tier 0's refactor.

### B8 — Living memory & consolidation
`reinforce` (a frequently-accessed note resists eviction) and
`reinterpret` (an old note's meaning shifts in light of new
experience) are both unbuilt — only `consolidate` (fold old notes into
a digest) and the pre-existing FIFO `forget` exist. Needs per-note
salience/access tracking across all five pillars — see Tier 3 item 24.

### B9 — Self-model & world-model per pillar
Effectively CLOSED — "how it relates to the others" was B9's one
named gap when this section was written, and B4's inter-pillar message
bus (shipped) already covers it. No further action needed here;
flagged in case a fresh audit disagrees.

---

## Part C — The Seam (Body ↔ Mind co-evolution)

### C1 — Perception channel (Body → Mind)
CLOSED. Salience-ranking (the one real gap found) is shipped.

### C2 — Intention channel (Mind → Body)
Most of the spec's own named pillar-emitted intentions (invent tech,
set custom, change law, reorganize institution, shift land use,
domesticate, build, propose experiment) aren't pillar-emitted
intentions at all yet — they're separate deterministic/LLM mechanics
untouched by the five-pillar refactor. Not a validation gap (every
Body-touching write that DOES exist today is validated) — a coverage
gap that mostly waits on Tier 0's bigger refactor to even become
relevant.

### C3 — Player ↔ Pillar chat
"Pillars may initiate contact" (today: strictly player-initiated via
`/ask/{pillar}`) — flagged as real future scope in the doc itself, not
silently dropped.

### C4 — The acceptance gate as law
The review-time half (reject isolated mechanics, reject state no
system observes) is a standing human discipline, followed but never
automated. The RUNTIME half — an auditor that actually retires
persistent state nothing reads — doesn't exist. See Tier 2 item 16.

### C5 — Co-evolution loop
Not a discrete task — the emergent end-state every other item above
feeds. Worth re-reading this item's own one-paragraph description
after any major Tier 0/1 push, as a sanity check on whether the loop
is genuinely turning unattended yet.

---

## Addenda from a deep re-pass of the checklist doc

Two things the per-item sections above don't fully surface, found by
reading the doc's own footer/roadmap-appendix sections end to end
rather than stopping at the per-item write-ups:

- **A11's R7 native-port deviation has a different justification than
  most.** Every other flagged "not yet ported to C++" item in this
  document (weather, terrain evolution, disasters) is deferred because
  it's genuinely low-density/not-a-measured-hotspot. `world/hydrology_
  field.py` is deferred for a DIFFERENT reason, per its own module
  docstring: it's a from-scratch mechanism whose exact shape needs
  live validation before locking into a compiled interface — worth
  knowing before assuming it's just next-in-line for the same
  low-density reasoning as its neighbors.
- **A loose thread in the source doc itself, not a code gap:** the
  Master Checklist's own closing section ("Open design decision")
  states the Humans-collective-vs-individual-NPC disagreement question
  formally "needs an explicit user decision before step 14 ships."
  Step 14 (B7) DID ship (v1.12.0) — but by adopting the doc's own
  stated *default* ("individual acts locally, collective sets the
  mood/direction"), not via a fresh explicit confirmation matching
  that footer's literal requirement. Functionally resolved (the
  default is sound and already load-bearing in shipped code); flagged
  here only because the checklist doc's own footer note was never
  updated to reflect that resolution, and a future reader taking that
  footer at face value could wrongly conclude B7 never really shipped.
  No code action needed — an optional one-line correction to `docs/
  MASTERCHECKLIST-2026-07-22.md`'s own footer, if that doc is ever
  revised again.

No further items were found beyond what's already recorded in the
Part A/B/C sections above — every "remain(s) open, flagged"/"NOT
attempted"/"NOT built" occurrence in the source doc (cross-checked via
direct search, not sampling) traces back to something already listed
in this roadmap.

---

## C++ native-porting backlog

Per CLAUDE.md's own standing R7 note (Engineering Constitution, "the CA
engine's remaining Python surface") — the authoritative, currently-
tracked list, not independently re-derived here:

- `world/weather.py` — the core blend function is ported (`cpp/src/
  weather.cpp`); the rest of the module (spatial-region handling)
  is not confirmed ported. Worth a direct check before assuming either
  way.
- `world/terrain_evolution.py` — same "not yet a measured hotspot"
  status as weather.py originally had; revisit under R7's "write new
  code in C++ from the outset" rule for anything added to it going
  forward, and consider porting the existing local-activity/climate-
  drift-adjacent hot loops opportunistically.
- `world/disasters.py` — not yet ported.
- `world/hydrology.py`/`world/hydrology_field.py` — not yet ported; a
  natural pairing with the A11 hydrology work above, since a real
  erosion/groundwater expansion would be new code anyway (R7: write it
  in C++ from the start rather than porting old code later).
- `economy/farms.py` — largely ported already (`cpp/src/farm_grid.cpp`,
  `soil_fertility.cpp`, `wilt_farms.cpp`); confirm nothing newer
  (nutrient cycling, A11 moisture-yield coupling) has been added back
  in pure Python since.
- `settlement/buildings.py`'s decay/repair math — largely ported
  (`cpp/src/settlement_decay.cpp`) per CLAUDE.md's native-module list;
  confirm this pass's newer ruin-scar/layout-grammar/architecture-
  grammar additions haven't reintroduced un-ported hot-path Python
  (they're metadata/scoring, not per-tick decay math, so likely fine —
  worth a direct read-through rather than an assumption).
- **New code discipline (already in force, not a backlog item):** any
  brand-new mechanic inside the CA/physical-substrate domain (weather,
  terrain evolution, agriculture, disasters, hydrology, ecology) is
  written C++-first from its very first commit — pybind11 binding,
  pure-Python fallback, randomized-equivalence + `verify_native_soak.
  py` verification — per R7. This is a standing rule for future A1-A21
  work above, not a separate task to schedule.

**Recommended first step if this backlog is picked up:** a direct
`grep`/read pass confirming exactly which of `world/weather.py`/
`terrain_evolution.py`/`disasters.py`/`hydrology_field.py` still run
hot per-tick loops in pure Python today, since this document's list
above is inherited from CLAUDE.md's own note rather than freshly re-
verified against current source — the R7 section itself flags this
as "the backlog... is unchanged in shape" from an earlier snapshot,
not a live-verified inventory.
