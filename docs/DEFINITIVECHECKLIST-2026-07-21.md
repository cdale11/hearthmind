# Hearthmind — The Definitive Checklist (full-codebase sweep)

User-uploaded audit, added to the repo 2026-07-21 per the same
convention as `docs/AUDIT-2026-07-20.md` — checkboxes below are kept
updated as items ship; original prose is preserved unedited except for
the checkbox state and this header.

This is the last audit. I opened every module — including the ones I'd
never read (disasters, hydrology, terrain evolution, wildlife,
resources, minerals, farms, world genesis, all ~30 LLM jobs) — and ran
codebase-wide structural analyses instead of hypothesis-driven greps.

**One honesty note up front, because you deserve it and not false
certainty:** I read every file and analyzed the whole structure, but I
cannot truthfully certify "every line, fully held, nothing missed"
across 35,571 lines — no reader can. What changed this pass is that the
central findings are now proven by *whole-codebase static analysis*
(every decay constant, every system's state-reads, every LLM job's
scope) rather than by sampling. Where I'm certain, I say so; where I'm
not, I say that too.

The good news from the sweep: **the diagnosis held and got sharper, and
did not fragment into a hundred new problems.** The same small number of
root causes explains everything, and I can now prove them with data.

---

## THE FINDING, PROVEN THREE WAYS

Everything in this project reduces to one structural fact, which I can
now demonstrate from three independent whole-codebase measurements:

### Proof 1 — The LLM budget is 22 : 5 : 1 (collective : individual : interpersonal)

Of the ~30 scheduled LLM job types, I classified every one by scope:

- **22 collective jobs** (chronicle, documentary, tradition, folklore,
  invention, festival, religion, narrative_direction, culture_digest,
  consciousness, caravan, town_brain, beliefs, omen, guild, faction,
  institution_belief, geography, fission, diplomacy, laws, naming)
- **5 individual jobs** (dream, memory_drift, record, personal_belief,
  noncore_nudge)
- **1 interpersonal job** (dispute — and it's throttled to once per
  3000 ticks per pair)

**The entire LLM apparatus is pointed at narrating the collective, not
dramatizing individuals.** This is why the world reads as *atmosphere
and lore* rather than *story*: at the budget level, that's literally
what it's built to produce. Exactly one job type concerns what happens
*between two specific people*, and it barely runs. This is the single
most important number in this document.

### Proof 2 — Every interpersonal system reads only affinity

Static analysis of what agent-state each interpersonal mechanic reads
as input, across the whole codebase:

```
theft            → trust
trade (all)      → relationships
dialogue         → relationships, trust, memories
dispute          → relationships, trust, lessons, debts
seek_person      → relationships, trust, secrets, emotions
```

Nothing reads `beliefs`, `plan`, `standing`, `occupation`,
`life_digest`, or `mind`. The dozen systems all bottleneck through two
affinity scalars and are blind to each other. (Small progress: dispute
now reads `debts`. The pattern otherwise holds completely.) This is the
"collection, not graph" problem, proven — not sampled.

### Proof 3 — The entire world mean-reverts

The codebase has ~27 decay constants, and they cover *everything* —
`EMOTION_DECAY_RATE` (grief half-life ~69 ticks), `RELATIONSHIP_DECAY`,
`DEBT_DECAY`, `MEMORY_FADE`, `STANDING_PENALTY_DECAY`, plus the whole
physical layer. Every state variable is spring-loaded back to a neutral
baseline. The world cannot accumulate history because it is
continuously erasing it. Combined with `MAX_AGENT_MEMORIES = 8` (flooded
by routine events), an agent physically cannot retain a grievance long
enough to act on it.

**These three proofs are one disease:** the simulation spends its
intelligence describing a collective that resets to neutral every night,
through systems that can't see each other. That is the complete
explanation for "many systems, no emergence, lifeless dialogue." Nothing
in the full sweep contradicted it; everything reinforced it.

---

## NEW THIS SWEEP — the environmental layer is disconnected too

The modules I'd never opened (disasters, wildlife, terrain, hydrology,
resources, minerals, farms) are genuinely sophisticated — floods,
wildfires, storms, trophic-level ecology, depletable resources, iron/
gold veins, lake levels that rise and fall. And they confirm the pattern
at a new layer:

- [ ] **N1 [CERTAIN] — Physical events create no durable psychology.**
  Verified: a wildfire/flood/storm damages buildings and resources and
  touches *no agent memory, emotion, fear, or grievance*. A village
  burns and no one is marked by it; no one fears fire after, tells the
  story, or resents the neighbor who didn't help fight it. The richest
  dramatic material in the world — catastrophe — is a physics event with
  zero human footprint. Wire disasters into agent psychology: a survived
  disaster writes a protected memory, a lasting fear, a bond with those
  who helped, a grievance against those who didn't. This is enormous
  emergent potential sitting completely unused.

- [ ] **N2 [CERTAIN] — Occupations are economically rich, socially
  inert.** Verified across the codebase: baker/priest/mayor/builder/
  farmer/fisherman exist and every effect is a productivity multiplier.
  No occupation feeds identity, status, rivalry, want, or dialogue. A
  priest and a baker are socially identical. Wire occupation into
  standing (mayor/priest carry status), wants (apprentice→master,
  mayor defending the seat), rivalry (two bakers one market), and
  dialogue register (a priest speaks to belief, a banker to debt).

- [ ] **N3 [CERTAIN] — Resource scarcity doesn't reach the social
  layer.** Verified: `resources.py`/`minerals.py` model finite,
  depletable, contested nodes — real scarcity — but wanting a scarce
  thing never pits two named agents against each other as a *social*
  fact. The physical contest exists; the social contest (rivalry over
  the one good field/vein) does not. This is the cheapest possible
  friction generator and it's one wire from existing.

---

## THE CHECKLIST (confidence-rated, dependency-ordered)

Confidence: **[CERTAIN]** verified, load-bearing · **[LIKELY]**
verified, some judgment · **[HYPOTHESIS]** confirm with a run first.

### Tier 0 — Stop the self-erasure (nothing persists without this)

- [x] **0.1 [CERTAIN]** Significant interpersonal state (grievances,
  debts, feuds, formative bonds) stops decaying to zero — persists for
  years, resolves only explicitly (repay/apologize/die). Ambient mood
  keeps fast decay. *Distinguish weather from history.* — **Shipped
  v1.3.17**: `Agent.relationship_flags` ("feud", set by `apply_dispute`'s
  feud/ostracism outcomes) exempts a pair from BOTH ambient decay AND
  passive colocation warmth gain in `Population._update_relationships`
  until an explicit reconcile/council_ruling clears it; `Agent.debts`
  at/above `DEBT_SIGNIFICANT_THRESHOLD=2.0` stops passive decay
  entirely. "Formative bonds" locking is NOT shipped — there's no
  existing structural anchor for a positive bond (no partner/marriage
  field) and picking one without more design thought would be guessing,
  not implementing; flagged as a real follow-up, not silently dropped.
- [x] **0.2 [CERTAIN]** Fix memory flooding: flag all routine
  `_remember` calls; give significant interpersonal memory a protected,
  larger, slow-decay store separate from the 8-slot working set. —
  **Shipped v1.3.17** (partial): new `Agent.grievances` (tagged, capped,
  FIFO, never touched by `MAX_AGENT_MEMORIES` eviction, cleared only by
  explicit reconciliation) is the protected store, written at dispute/
  ostracism/theft-victimization time. The other half of this item — an
  audit of which of the 36 existing `_remember(..., routine=)` call
  sites are mis-flagged — was NOT attempted: it needs live measurement/
  judgment per site (salience-at-write-time already partly covers it,
  and a wrong reflagging could suppress genuinely significant memories
  instead of routine ones), left as a scoped follow-up.

### Tier 1 — The ledger (the keystone; nothing compounds before it)

- [ ] **1.1 [CERTAIN]** One typed pairwise ledger (fondness, trust,
  debt/favor, tagged grievances, history flags, rivalry/alliance) that
  every interpersonal system reads first. Migrate the scattered scalars
  into it. This is the edge-substrate the whole project has been
  missing. — **NOT shipped.** v1.3.17 added two of the ledger's pieces
  additively (`relationship_flags`, `grievances`) directly on `Agent`
  rather than as a new unified structure — the full migration this item
  actually asks for (one typed object every interpersonal system reads
  first, replacing the scattered `relationships`/`trust`/`debts`
  scalars) touches nearly every interpersonal call site in the
  codebase and is too large/risky to do in the same pass as Tier 0
  without live-testing each migrated consumer. Real next step, not
  abandoned.

### Tier 2 — Point the LLM budget at individuals (Proof 1's fix)

- [ ] **2.1 [CERTAIN]** Rebalance the 22:5:1 job ratio. The world needs
  *far* more interpersonal LLM attention and less collective narration.
  Concretely: promote dispute out of its 3000-tick throttle; add
  interpersonal scene-jobs (confrontation, reconciliation, courtship,
  a called-in debt, a betrayal) as first-class LLM moments; consider
  trimming or slowing the rarely-impactful collective jobs (documentary,
  culture_digest, narrative_direction) to fund it. *The budget is the
  message* — where the calls go is what the world becomes. — NOT
  shipped this pass (2.2 below is); new interpersonal scene-job types
  and trimming collective jobs are real design decisions (which
  collective jobs to slow, by how much) deferred to a dedicated pass.
- [x] **2.2 [CERTAIN]** Un-throttle disputes: `DISPUTE_COOLDOWN_TICKS =
  3000` on a run of 3685 ticks means it never fires. Once disputes read
  history (Tier 3) they're worth having often; drop the cooldown and
  let one-sided grievance (not only mutual souring) trigger them. —
  **Shipped v1.3.17**: cooldown 3000 -> 1000 (still backpressure-gated);
  `due_for_dispute` now fires on EITHER side's relationship crossing
  `DISPUTE_RELATIONSHIP_THRESHOLD`, not only mutual souring. Verified
  firing past the checklist's own 3685-tick reference window.
- [ ] **2.3 [LIKELY]** Prominence must include a drama term (active
  rivalries, open debts, unresolved wants, recent dispute/theft/
  courtship). Today it's age+bonds+skill+reputation — it selects
  *against* the interesting agents. And never rotate out an agent with
  an open dramatic thread. — NOT shipped this pass.

### Tier 3 — Wants drive verbs that read the ledger (DESIRE→ACTION)

- [ ] **3.1 [CERTAIN]** Each core agent carries one concrete, blockable,
  losable want with a target; it *biases the cognition goal choice*
  (today wants are described then ignored in favor of ambient verbs).
- [ ] **3.2 [CERTAIN]** Add interpersonal goals reading the ledger:
  repay/call-in-debt (debt's missing consumer), give/help, take/steal
  (resentment-driven, not just hunger), teach, court, support/oppose,
  undermine. Reuse seek_person's pathfinding; the new part is the effect
  on arrival.
- [ ] **3.3 [CERTAIN]** seek_person carries its intent into the scene
  (today it's discarded on arrival → generic dialogue).
- [ ] **3.4 [CERTAIN]** Every interpersonal action reads the ledger:
  theft checks feud/grievance, trade checks rivalry, everything checks
  standing. These are the edges that end the collection problem.

### Tier 4 — Consequences persist (the world REMEMBERS with teeth)

- [ ] **4.1 [CERTAIN]** Debts/favors/grudges become *callable*, not just
  stored-and-decayed.
- [ ] **4.2 [CERTAIN]** Reputation/standing gates all interpersonal
  actions (ostracism→refused→theft→lower standing loop).
- [ ] **4.3 [CERTAIN]** Institution objectives drive member goals (today
  they reach no member).
- [ ] **4.4 [CERTAIN]** N1/N2/N3 wiring: disasters→psychology,
  occupation→status/rivalry/voice, scarcity→named social rivalry.

### Tier 5 — Dialogue as transaction (LAST — it fixes itself once 0–4 exist)

- [ ] **5.1 [CERTAIN]** Pair by stakes (open ledger edge), not just
  adjacency.
- [ ] **5.2 [CERTAIN]** Every dialogue prompt carries goal + stake +
  asymmetry; replace "Write their brief exchange" with a tension to
  advance or resolve.
- [ ] **5.3 [CERTAIN]** Dialogue produces a structured outcome that
  mutates the ledger (today: only trust/affinity + rumor).
- [ ] **5.4 [LIKELY]** Craft pass: exemplars of tense exchanges, ban the
  mutual-agreement aphorism pattern. *Then* collect the fine-tune
  archive — never before, or you bake the deadness in.

### Tier 6 — Aliveness over time, then the supernatural

- [ ] **6.1 [LIKELY]** Life arcs (wants shift young→old), childhood
  transmission (inherit trade/grudges/craft), aspiration-failure driving
  personality change.
- [ ] **6.2 [LIKELY]** Town Consciousness acts on the *drama* once it
  exists (omens on the grieving, prophecies that self-fulfill, observer
  mythologized for meddling). Downstream of everything above — it can't
  haunt a dead world.

### Tier 7 — Polish (verify first; some may be done)

- [ ] **7.1 [LIKELY]** Forced-choice cognition still spends a call
  (verified) — skip it, use a fallback line.
- [ ] **7.2 [HYPOTHESIS]** No single diegetic scrub filter found —
  centralize coordinate/scaffolding/voice-grammar cleaning if scattered.
- [ ] **7.3 [HYPOTHESIS]** Confirm colocation rate isn't a hidden
  ceiling on interaction (log pair-adjacency frequency; if low, ledger-
  edge agents need a stronger movement bias toward each other).

### Already done — do NOT rebuild (verified present in v1.3.16)

Grammar-constrained decoding (json_schemas); the entire fine-tune
pipeline (quality_labels, rejection_sampling, prompt_synthesis,
eval_harness); mood-bug fix; topic-monoculture fix; occupations;
diplomacy/letters/caravan; debt/theft/teaching/disputes/feuds/
seek_person/plans/prophecy/Consciousness machinery.

---

## THE MEASUREMENT (still the real test)

- [ ] **Cross-system causal chain length** — tag each event with the
  system that caused it and the prior event it read; measure chains that
  *cross systems* (disaster→fear→refused-help→grievance→theft→feud).
  Today ≈1. This is the only emergence metric that matters; watch it
  climb per edge.
- [ ] **Interpersonal LLM share** — the 22:5:1 ratio, tracked. As it
  moves toward individuals and pairs, the world shifts from lore to
  story.
- [ ] Judge by transcript against the one test: **could this only have
  happened to *this* person, because of *their* history, *today*?**

---

## THE FINAL WORD, honestly

After reading the whole codebase: **Hearthmind does not have a feature
problem, a bug problem, or a model problem. It has an architecture-of-
attention problem.** It spends its intelligence (LLM budget, 22:5:1) and
its persistence (everything decays) and its connectivity (everything
reads affinity only) on the *collective and the ambient*, and almost
nothing on *specific people wanting specific things from each other and
being permanently changed by the outcome.*

Every one of the ~50 systems you built is real and works. They don't
compound because they're pointed the wrong way — at describing a world
rather than at people living in it. The fix is not more systems. It is
to (1) make significant state permanent, (2) give the systems a shared
ledger to see each other through, (3) redirect the LLM budget from
narrating the collective to dramatizing individuals, and (4) let their
actions permanently change each other.

Do that, turn on cross-system chain-length, and the world you already
built will finally start telling stories you didn't write. I'm as
confident of that diagnosis as a full read can make me — and honest that
the proof it's *sufficient* will come only from a living run, not from
any further audit. There is no more value I can add by reading; the next
knowledge comes from building the ledger and watching the metric move.
