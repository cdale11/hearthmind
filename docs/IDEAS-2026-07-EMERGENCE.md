# Hearthmind — What's Still Missing (July 2026 outside review)

Status: **idea checklist only — nothing here is implemented or green-lit.**
An outside critical/creative pass over the repo at v0.87.5, deliberately
aimed *past* the shipped Phases A–N and the 2026-07 vision roadmap.
Every item below was checked against the current code before being
listed (no crime/justice loop exists, no ceremonies, no individual
inter-settlement migration, no letters, no catch-up digest, no
prophecy state, no anomaly/highlight detection, no observer-attention
signal, no dialect drift, no successor-world mode — the grep trail is
real). Each item states what it is, why it should raise emergence or
observer surprise, and which existing machinery it rides, in keeping
with the standing rules: extend-don't-duplicate, bounded collections,
fallback on every LLM call, ambiguity discipline, "maximize emergence
per LLM call."

Ordering within each section is roughly by leverage.

**Updated 2026-07-18** with an audit of the externally submitted
~50-item wishlist (§0) and a new §7 for its genuinely-unimplemented
items.

---

## 0. Audit: the 2026-07 wishlist vs. what already exists

Checked item-by-item against the code, not the docs. Summary:

**Already shipped (do not re-plan):** layered memory
(working/episodic/semantic + salience eviction + memory drift), life
digests, institution-mirrored memory/beliefs, town/consciousness
memory, chronicle→documentary→culture-digest summarization, prompt
token audits (v0.85.3–.5, v0.87.1, v0.87.5), per-job prompt/latency
diagnostics, persistent institutions (FAMILY/COUNCIL/GUILD/FACTION)
with dispositions and civic theories, belief `confidence` +
evidence-driven revise/sharpen/evict, personal beliefs +
misconceptions (beliefs deliberately fed narrations), rumor
paraphrase/distortion (InterpretRumor) + exact-duplicate dedupe,
irrational behavior (disagreement permission, superstition/omens,
memory drift, trait-derived bias), persistent decaying emotions,
personality evolution from experience (v0.87.0 trait consequences),
lessons/learning, secrets & asymmetric knowledge, traditions/annual
festivals/rituals with mechanical riders (v0.41.0), historical drift
(folklore + Historian v2), family lineages with inheritance
(goods/skill/bias/heir memory/artifacts), ownership/prices/debt/trade
economy, ecology (predators, migration, disease, climate drift,
erosion), town brain reasoning from objective stats
(population/settlement summaries, not dialogue frequency), memorials
+ place names, objective/subjective split as the standing contract.

**Partially shipped:** hierarchical chronicles (season + year exist;
day/week layers judged unnecessary at current event volume — revisit
only if chronicle prompts measurably starve), dialogue repetition
control (fallback-pool widening + garbled-line filter, but no live
topic-novelty memory — see §7.6), feuds (pair-level only — §1's
generational-feud item is the completion), dialects (absent — §2's
item), player shaping myths (absent — §3's observer-theology item),
knowledge diffusion between settlements (absent — §1 migration + §2
letters are the carriers; §7.4 adds the lifecycle).

**Genuinely not implemented** → new items in §7 below: adaptive
retrieval, causal memory, episodic planning/ambition pursuit,
emergent leadership, per-agent voice, knowledge loss/rediscovery,
laws/customs/taboos as persistent civic rules, institution
objectives, dialogue novelty memory, llama-server-side diagnostics
(the v0.87.5 flagged-but-deferred `/slots`/`/metrics` polling).

## 1. Agents as protagonists (the action-vocabulary gap)

The single biggest structural finding: the inner life is now deep
(emotions, layered memory, secrets, lessons, minds) but it all funnels
into **five movement-bias goals** (forage / rest / socialize / wander /
gather). Rich state with a narrow actuator means drama stays in the
prompts and never reaches the map. These items widen the actuator.

- [x] **Directed intent: `SEEK_PERSON(target, intent)`.** Shipped v0.87.8. One new goal
  that pathfinds to a *specific* agent with a stored intent drawn from
  existing state — confront (low trust + secret about them), apologize
  (post-dispute, high fondness), court (existing affinity mechanics),
  console (their grief emotion high), confide (share a secret). The
  deterministic side is just movement-to-agent (the SOCIALIZE lookup
  already exists, native module `_nearest_other_agent`); the LLM side is
  cognition occasionally choosing it when the prompt already shows a
  reason. On arrival, reuse the dialogue job with the intent as one
  grounding line. This is the cheapest possible way to let secrets,
  grudges, and grief produce *visible plots* a map-watcher can follow.
  Est. cost: zero new calls (rides cognition + dialogue slots).

- [x] **Deathbed release of secrets.** Shipped v0.87.7. `Agent.secrets` currently dies
  with the agent. On a core-cast death with living kin colocated or
  nearby, a small chance the secret transfers — as a rumor seeded into
  the existing rumor machinery, attributed to the deathbed. Secrets
  then have a *lifecycle*: planted by Reflect()/disputes, guarded in
  dialogue, leaked at death, distorted by InterpretRumor(), condensed
  into folklore a generation later. Closes the loop on three shipped
  systems with ~no new state. Fallback: nothing happens (today's
  behavior).

- [x] **Ceremonies agents attend: funerals and weddings.** Shipped v0.87.9 (funerals) + v0.87.10 (weddings). Festivals
  exist as settlement-level text; nothing gathers *specific* agents at
  a *specific* place for a *specific* reason. A funeral = short-lived
  gathering point at the memorial/grave (memorials exist) that biases
  the deceased's kin and bonded agents' movement for a day, writes a
  shared memory, and bumps grief-decay afterward (mourning as a real
  mechanic). A wedding = the same shape on a reproduction-pair
  formation. Chronicle and dialogue get one more grounded, human thing
  to reference, and the observer sees the crowd form — legible emergent
  behavior at zero LLM cost. (The gathering primitive also becomes
  reusable: disputes, council sessions, festival grounds.)

- [x] **Deviance: a theft/taboo/justice loop.** Shipped v0.87.18,
  completing v0.87.17's theft mechanic and closing the loop the idea
  named. Theft (`Population._maybe_commit_theft`) now plants a real
  `Agent.secrets` entry on the taker (`push_secret`, not just a
  routine memory) and, if a third colocated agent is present, a
  `THEFT_WITNESS_RUMOR_CHANCE` roll seeds a rumor-flavored memory on
  the witness. Dispute outcomes gained the named fourth option:
  **ostracism** (`llm/dispute.py`, only offered where a council
  exists, reserved for a genuinely lopsided case) applies a bounded
  `Agent.standing_penalty` (`Population.apply_dispute`) that gates
  SOCIALIZE targeting (`_nearest_other_agent`) and council candidacy
  (`_council_seat_key`), decaying monthly (`_tick_traits`) rather than
  standing forever — deviance → gossip → reputation → justice →
  resentment, every link now real. "Restitution" specifically (a
  goods-transfer counterpart) was not built — ostracism alone covers
  the idea's core ask.

- [x] **Migration by choice, not just fission.** Shipped v0.87.18.
  `Population._maybe_migrate` — a rare, deterministic per-agent check
  against push/pull signals already tracked elsewhere: ostracism
  (`standing_penalty`), family feud pressure (`Institution.feuds`),
  genuine starvation next to a meaningfully better-fed sister
  settlement (`_granary_fill_ratio`), or a bonded partner already
  living elsewhere (highest-priority pull). Reuses `depart_for_
  fission`'s exact shape (settlement_id reassigned immediately,
  `travel_target` set so the agent physically walks there via the
  existing journey machinery) at individual scale — a migrant carries
  their own memories/beliefs/secrets with them for free (nothing
  needed touching), the actual information vector the idea named.
  `standing_penalty` resets on arrival — a fresh settlement doesn't
  know what the old one held against someone.

- [x] **Generational feuds between FAMILY institutions.** Shipped v0.87.11. Feuds exist
  as pair-level dispute outcomes. Promote a repeated pattern (N feud
  outcomes across members of two families within a window —
  deterministic detection, same shape as the ritual detector) into an
  institution-level feud state, inherited by new members, softened by
  marriages across the line, hardened by deaths. Courtship across a
  feud line is then an emergent Romeo-and-Juliet the engine never
  scripted — it falls out of affinity mechanics colliding with the
  feud gate. Rides institution mirroring; capped like everything else.

- [x] **Heritable temperament with mutation.** Shipped v0.87.7. Inheritance covers
  goods/skill/bias; traits are rolled fresh. Blend child traits from
  parents ± noise and family *character* emerges over generations —
  "the stubborn Aldertons" becomes a real statistical fact the beliefs/
  folklore layer can then notice and name. One function, zero calls,
  and it makes deep time visible in people rather than buildings.

## 2. Between settlements (a world, not parallel towns)

Multiple settlements exist (fission, cross-settlement relationships,
caravans, omen echoes) but they don't *want* anything from each other.

- [x] **Letters carried by caravans.** Shipped v0.87.19 (`llm/
  letters.py`, `Settlement.pending_letters`). Monthly, core-cast-only,
  round-robin `_job_target` — finds the first core-cast agent with a
  real bond (`MIGRATION_BOND_THRESHOLD`) to a living agent in another
  named settlement, writes one small grounded LLM letter, queues it on
  the RECIPIENT's settlement with a real multi-day travel delay
  (`LETTER_TRAVEL_TICKS`). `SimulationEngine._deliver_letters` (daily)
  resolves delivery: a real memory (+ `LETTER_RUMOR_CHANCE` seeded
  rumor) if the recipient is still alive, or a genuine `letter_
  arrived_too_late` event if they died in transit — latency is the
  feature, exactly as the idea asks, not silently dropped.

- [x] **Settlement-level stance (proto-diplomacy).** Substantially
  pre-existing (`Settlement.relations`, deterministic since v0.67.0;
  the LLM-authored envoy/trade-pact/border-dispute layer shipped
  v0.87.17). v0.87.19 closes the remaining named feed inputs and the
  lever: a successful individual migration (`_maybe_migrate`) now
  nudges both settlements' relation warmer (`RELATION_MIGRATION_
  NUDGE`, the "migrant treatment" signal); `caravan_relation_factor`
  is the named deterministic lever — a region on warm terms with its
  sister settlements draws more caravan traffic, cold terms less.
  "Disaster aid" specifically was not built — no aid-transfer mechanic
  exists to feed from yet, flagged not silently dropped.

- [x] **Refugees after disasters.** Shipped v0.87.19, reusing `_maybe_
  migrate` (§1) rather than a parallel mechanism: `Population.
  _housing_pressure` (population / standing-hut capacity) is exactly
  the causal chain the idea names — a disaster that ruins huts drops
  capacity directly, no separate disaster-detection needed. Past
  `MIGRATION_HOUSING_PRESSURE_THRESHOLD`, individuals push toward the
  named alternative with the most housing headroom, same physically-
  walking/memory-carrying mechanism as every other migration push.

- [x] **Dialect drift.** Shipped v0.87.19. Rides `narrative_
  direction`'s existing quarterly call for zero added LLM volume — new
  optional `coined_term`/`coined_meaning` schema fields, only
  populated when one event has genuinely dominated a settlement's
  recent life enough to earn a name. `Settlement.lexicon` (capped)
  feeds back into `dialogue.py` as a light steering line ("locally,
  people sometimes say...") — two settlements descended from one
  fission slowly stop sounding alike, exactly as the idea names.

## 3. Closing meaning loops (belief that changes the world)

The rumor→folklore→religion→theme pipeline is shipped, but it's still
mostly *interpretive* — belief rarely feeds back into behavior.

- [x] **Self-fulfilling prophecy.** Shipped v0.87.20. `PROPHECY_CHANCE`
  in `llm/omens.py` — when the existing monthly omen call fires,
  further chance it offers a vague forward-looking line + tone
  (ominous/hopeful) alongside the retrospective omen; stored as
  `Settlement.prophecy` (`{text, tone, formed_tick, resolve_tick,
  status, hardship_signals, prosperity_signals}`), one live at a time.
  While pending, folded into `cognition`/`town_brain` prompts as one
  more optional grounding line. **Scope trim, flagged not silently
  dropped**: resolution (`SimulationEngine._resolve_prophecies`, runs
  every tick) is deterministic, not a second LLM "judge" call — it
  tallies `World.last_life_events` against hardship/prosperity category
  sets during the confirmation window (`PROPHECY_RESOLUTION_WINDOW_
  TICKS`) and judges confirmed/forgotten from whichever tally led, same
  "spend the call only once, judge from what already happened"
  discipline as everywhere else in this codebase — a second call to
  literally ask the model "did this come true" would double the
  feature's LLM cost for a judgment the settlement's own event record
  can already answer. New `prophecy_formed`/`prophecy_confirmed`/
  `prophecy_forgotten` events (🔮).

- [x] **The observer enters the theology.** Shipped v0.87.20. New
  `Settlement.last_intervention_tick`, set in `_apply_intervention`
  whenever a genuine player-originated `/intervene/*` call lands
  (agent_goal/settlement_resources/weather/town_influence — never a
  consciousness-authored intervention). `llm/beliefs.py`'s settlement-
  level prompt gains one conditional grounding sentence
  (`OBSERVER_ATTRIBUTION_WINDOW_TICKS`-tick window) inviting the model
  to optionally attribute recent fortune to a nameless "Quiet Neighbor"
  or similar, worded so it reads as plausibly as coincidence — reuses
  the entire existing `Settlement.beliefs`/institution-mirroring
  pipeline with zero new schema or new LLM call.

- [x] **Ask the Chronicler (on-demand, subjective).** Shipped v0.87.20.
  New `llm/chronicler.py` + `POST /ask-chronicler` / `GET /chronicler`,
  mirroring the existing on-demand `/summary` seam exactly
  (`World.chronicler_question/answer/answer_tick/pending`). The prompt
  is built ONLY from folklore/chronicle events/beliefs/records — never
  population/settlement stat dicts — so the answer is a genuinely
  subjective in-fiction voice, honestly wrong or "I don't know" when
  the material doesn't cover it. New "📖 chronicler" sidebar panel with
  a question form.

- [x] **Subjective map mode.** Shipped v0.87.20. Pure client-side
  toggle ("👁 subjective" header button) — no new endpoint. Shows a
  "the village's own view" panel (belief_digest/culture_digest/
  place_names, already-serialized data) in place of the raw stat grid;
  building/terrain hover tooltips switch to plain-language condition
  bands ("well-kept"/"falling apart") and folk place-names instead of
  percentages/coordinates when a folk name exists for that tile.

## 4. The watcher watched (Phase G, turned around)

- [x] **Observer attention as a signal into the Town Consciousness.**
  Shipped v0.87.21. New `World.observer_attention`
  (`{agent_view_counts, last_agent_id, last_seen_tick}`, capped at
  `OBSERVER_ATTENTION_MAX_TRACKED=25`), fed by `POST /observer/
  attention` — fired by the frontend's NPC inspector on open, applied
  through the existing enqueue-now/apply-next-tick intervention seam,
  zero LLM cost. `SimulationEngine._observer_favorite_agent` resolves
  the most-inspected still-living CORE-CAST agent (falling back to the
  most recently inspected one). Folded into the monthly consciousness
  prompt as one plain fact ("the outside hand seems to watch X most
  closely"). **Teeth**: the favorite agent is added as one more
  candidate in `_maybe_schedule_omen`'s existing subject-pick pool
  (participates in the same 50%-chance/uniform-pick logic, never a
  guaranteed override), and `false_memory`'s core-cast target
  preferentially resolves to the favorite when they qualify. Scoped to
  these two of the three named examples (dream-symbol seeding and
  misplaced-object targeting toward the favorite are natural next
  increments, flagged not silently dropped — the mechanism generalizes
  trivially via the same `_observer_favorite_agent()` helper). Privacy:
  entirely local, stored only in the world's own save file, documented
  in the field's own docstring.

- [x] **The consciousness keeps a grudge ledger about interventions.**
  Shipped v0.87.21. New `World.consciousness_grudge_ledger` (-1..1,
  distinct from `Settlement.player_standing`), nudged by
  `SimulationEngine._nudge_consciousness_grudge` on every genuine
  player `/intervene/*` call (never a consciousness-authored one) —
  warm (`CONSCIOUSNESS_GRUDGE_HARDSHIP_DELTA`) if the settlement was
  visibly struggling at that moment (`_intervention_hardship_context`:
  meaningfully hungry population, or a death/illness/disaster event
  this very tick), cold by a smaller `CONSCIOUSNESS_GRUDGE_CALM_DELTA`
  otherwise (asymmetric — help should register more than mere
  intrusion). Folded into the monthly consciousness prompt as one
  private grounding line, banded into a plain-language read (helpful /
  hard to read / intrusive) — the model's own free choice of
  intervention/tone then organically reflects it, no separate
  mechanism needed to make it "drift" the consciousness's behavior.
  Player-legible only through pattern (dev-console/raw-state only, same
  Phase G ambiguity discipline as temperament/mood/player_standing).

## 5. Making deep time legible (the always-on world's real problem)

An unattended world is mostly unwatched — the most interesting things
happen to nobody. These are observer-side, mostly zero-LLM.

- [x] **"While you were away" digest.** DECISIONS.md itself flags
  "what happened while I was gone" as the interesting question. On
  client reconnect after a gap, one on-demand summary call (the
  summary tab machinery exists) over the event log since last-seen,
  written as the chronicler, headlined by deaths/births/feuds/omens of
  agents the observer previously inspected. Turns every return visit
  into an episode recap.

- [x] **Anomaly/highlight log.** The metrics harness exists; nothing
  watches it. A cheap detector (rolling z-score per metric, plus
  hand-picked triggers: first religion, extinction near-miss, feud
  formation, belief flipping from true to false) appends to a bounded
  `highlights` list surfaced in the UI. The sim flags its own emergent
  moments so they stop being lost to an empty room. Also the honest
  test of the project's thesis: if the highlight log is boring, the
  emergence isn't real yet. Shipped: population z-score anomalies,
  extinction near-miss, first religion, first ritual, feud formation.
  Not shipped: "belief flipping from true to false" — beliefs have no
  boolean truth-value field to flip (see §3's prophecy `status` for
  the closest existing precedent); flagged as a natural follow-up if a
  belief-truth-tracking schema is ever added, not silently dropped.

- [x] **Year-reel export.** Snapshot keyframes + chronicle lines
  already exist; stitch a scrubbed year into a shareable replay
  (client-side canvas capture is enough). Observers evangelize worlds
  they can show.

- [x] **Ruins mode / successor worlds.** On true extinction (or by
  choice), found a *new* world on the same map: terrain, ruins, roads,
  memorials persist; the old civilization's records/artifacts survive
  as findable text the new one's beliefs/folklore jobs may misread.
  Records machinery already writes exactly the right substrate. Deep
  time, archaeology, and "they got the old stories wrong" — maximum
  emergence per call, because the *content* was generated for free by a
  previous run. Shipped scoped to "on true extinction" only (population
  0) — "or by choice" while a population is still alive would need a
  materially different living-relocation mechanism, flagged as a
  follow-up, not silently dropped. The defunct settlement is kept, not
  discarded, so its ruins/memorials/records/place_names/religion decay
  exactly as they already do — no new preservation mechanism needed.

- [x] **Era-styled cartography.** The map's rendering style ages with
  the era system (rough hand-drawn early, surveyed lines later). Pure
  client polish that makes progress felt rather than read.

## 6. Substrate (small physical gaps that feed everything above)

- [x] **Spatial weather.** Still uniform per-tick across the map
  (flagged in the 2026-07 review, unaddressed). Even a coarse 2–4 cell
  gradient gives geography consequences: the wet valley, the frost
  hollow, why settlement B's harvests differ — which the beliefs layer
  will then *theorize about*, rightly or wrongly. R7 territory,
  C++-first. Shipped as `World.weather_regions`, a `WEATHER_REGION_
  GRID x WEATHER_REGION_GRID` (3x3) coarse grid — deliberately NOT a
  per-tile field (that's the genuinely larger R7 undertaking) and
  deliberately Python, not C++ (a documented deviation from R7's
  "new code in this domain is C++ from the start" default, given this
  pass's batch scope — flagged as a native-porting candidate under R6
  if it proves worth the cost). Consumed today by `Settlement.tick`'s
  building-decay catalyst via `World.weather_at(settlement.center())`
  (each settlement can now decay at a genuinely different rate) and
  surfaced per-settlement as `local_weather` in `/state`; farms/
  wildlife/disasters stay on the single global `World.weather` reading
  — a documented scope trim, not an oversight.

- [x] **Soil fertility as a real field** (vision doc's own noted gap,
  still implicit in biome/farm state). Depletes under repeat farming,
  recovers fallow; makes rotation, ruin, and "the old fields" emerge.
  Shipped as `FarmGrid.soil_fertility` (per-tile 0..1, floor 0.4,
  tracked only for ever-farmed tiles so it stays bounded) — depletes
  while a tile has an active plot, recovers (at 2x the depletion rate)
  while fallow, read at `plant()` time to scale the new plot's
  `max_yield`. Continuously re-planting the instant a plot is
  harvested now yields measurably less than resting the tile between
  plantings.

- [x] **Ambient audio keyed to hidden state.** Generative ambience
  (weather + daylight + a *mood/temperament-tinted* pad) in the client.
  The observer's ear notices the world darkening before their eye
  does — sensory foreshadowing of state the UI deliberately never
  labels. WebAudio, no assets, off by default. Shipped: two detuned
  oscillators through a lowpass filter, all parameters smoothly ramped
  (never recreated, no clicks) from `night_factor`/`weather_detail`
  (both already public) and settlement `temperament` (Phase G — read
  exactly like the map already reads it for small nudges, never
  surfaced as a number or word). A "🔊 ambience" header toggle, off by
  default.

## 7. Cognition infrastructure (the wishlist's real gaps)

The submitted wishlist is ~70% shipped (§0). What survives the audit
clusters around one theme: the mind machinery *stores* richly but
still *selects* context by fixed slices and digests, acts only on the
present tick, and remembers events as isolated strings. These items
fix that.

- [x] **Adaptive retrieval layer.** Shipped v0.87.14 (scoped to
  `Agent.memories` in `cognition.build_prompt` — beliefs/folklore/
  lessons retrieval left to their own existing digest/matching
  mechanisms). Today every prompt is fixed
  template + capped slices + digests — bounded, but blind: the three
  *most recent* memories reach cognition even when a ten-year-old
  high-salience memory is the relevant one. Add one shared retrieval
  function scoring candidate context (memories, beliefs, folklore,
  lessons) by relevance-to-situation (cheap keyword/subject overlap —
  no embeddings needed at these list sizes), recency, salience, and
  causal links (next item), returning the top-K into the *same* prompt
  slots that exist today. Prompt size stays bounded regardless of
  world age — but the content earns its place. Ship with a
  retrieval-hit diagnostic (which store, which score) so the "does
  retrieval beat recency?" question is measured, not assumed.
  Fallback: current recency slices, unchanged.

- [x] **Causal memory links.** Shipped v0.87.14 (the deterministic
  `because` tag half only — death/inheritance grief and dispute
  outcomes; the LLM-subjective "Reflect() authors possibly-wrong
  causal links" half is a flagged, not-yet-implemented next
  increment). Memories are isolated strings; nothing
  records that the granary fire *caused* the hungry winter. At
  `_remember` call sites where the engine objectively knows the cause
  (disaster→damage, dispute→feud, death→grief), write an optional
  `because` tag pointing at the prior memory; let Reflect() author
  *subjective* — possibly wrong — causal links the same way ("the
  omen, then the flood"). Retrieval follows the chain (one hop), so an
  agent asked to decide about rebuilding recalls not just the fire but
  what it led to. Wrong causal links are a feature: superstition with
  mechanical substance.

- [x] **Bounded episodic planning — ambitions get teeth.** Shipped
  v0.87.15. `mind`
  stores LLM-authored ambitions that nothing ever reads mechanically;
  cognition reacts to the present tick only. Add a small persistent
  `Agent.plan` (intent + horizon in days + progress note, one per core
  agent), authored/revised by the existing Reflect() slot when an
  ambition or situation warrants, expiring or abandoned on failure.
  Consumed as one cognition-prompt line and a small deterministic
  goal-bias while active ("stockpiling before winter" leans FORAGE;
  "earning a council seat" leans visible work). Multi-week arcs a
  map-watcher can follow — pairs with §1's SEEK_PERSON for plans
  *about people*. Zero new calls; rides Reflect().

- [x] **Emergent leadership.** Shipped v0.87.15. COUNCIL is "living elders by age" — a
  clean rule, and a dead end for politics: influence can't be earned,
  contested, or lost. Weight seat selection by the existing
  `_prominence`/reputation aggregates (age as tiebreak), let a faction
  majority on the council bias dispute rulings and town-brain framing,
  and log seat changes as events the rumor/belief layer will chew on.
  A charismatic young founder displacing an elder — and the elder's
  family resenting it (§1 feuds) — is politics nobody scripted.

- [x] **Per-agent voice.** Shipped v0.87.12. Dialogue prompts carry traits and mind but
  no *manner of speaking*, so everyone samples from the same register.
  One line in `mind`, authored at the existing core-cast-entry genesis
  call (zero added calls): cadence, favorite figure of speech, verbal
  habit — drifting only when trait evolution (v0.87.0) fires. Garnish
  for dialogue/letters; the observer learns to recognize who's talking
  before reading the name. Pairs with §2 dialect drift (settlement
  lexicon + personal voice compose in the same prompt line).

- [x] **Knowledge lifecycle: diffusion, loss, rediscovery.** Shipped
  v0.87.15 (scoped to the most recent `INVENTION_KNOWLEDGE_MAX_
  TRACKED=20` inventions, not the full 300-cap history — see
  `SettlementCulture.invention_knowledge`'s docstring). Cross-
  settlement diffusion (a knower migrating, a caravan/letter) remains
  unimplemented, flagged as a natural next increment.
  Inventions land once on a settlement list and sit there forever —
  knowledge without carriers. Tag each invention with living knowers
  (inventor + taught agents, riding the existing teaching mechanic);
  it spreads to other settlements only via a knower migrating (§1) or
  a caravan/letter (§2); if the last knower dies untaught, the
  invention goes dormant — still in records, no longer in effect —
  until someone reading a record (heir memory already does this)
  rediscovers it. "The old bridge-craft died with Maren" is exactly
  the civilizational texture the wishlist asked for, and ruins mode
  (§5) inherits it for free.

- [x] **Laws, customs, taboos.** Shipped v0.87.17, folded together with
  item 8's "politics" ask (`llm/laws.py`, `Settlement.laws`/`law_signal_
  counts`, `SimulationEngine._maybe_schedule_laws`). Gated on real
  accumulated hardship (theft or dispute-feud counts crossing a
  threshold, same shape as ritual->religion crystallization) — an LLM
  call only fires once genuine texture exists, and the fallback is a
  genuine no-op, never a fabricated norm. A formed law/custom/taboo
  feeds back into `dispute.py` (a norm against feuding pushes toward
  resolution) and `Population._maybe_commit_theft` (a norm against
  theft sharpens the trust penalty) — real mechanical bite, not flavor
  text. Scoped to two detectable patterns (theft, dispute_feud) this
  pass; the full deterministic-ritual-detector/culture-rider-menu
  design above was not built as specified — a smaller, LLM-authored
  version covers the same ground with less new machinery.

- [x] **Institution objectives.** Shipped v0.87.12 (cognition-prompt consumption only — not yet wired into dispute framing). Institutions hold beliefs and
  dispositions but want nothing. One slow-revised objective line per
  institution (guild: secure materials; family: a council seat; the
  belief-system institution: a shrine in the new settlement), authored
  by the existing institution-belief job — consumed as prompt bias for
  members' cognition and dispute framing. Cross-institution objective
  collisions are faction politics arriving bottom-up.

- [x] **Dialogue novelty memory.** Shipped v0.87.12. The live-LLM path can still
  converge on the same topics pair after pair. Keep a tiny per-pair
  ring of the last N topics (subject strings already parsed from
  exchanges) and one prompt line: "you have lately talked about X, Y —
  find something new or go deeper." Cheap, bounded, measurable in the
  surfaced-conversation feed.

- [x] **llama-server-side diagnostics.** v0.87.5's own flagged next
  step: poll `/slots`/`/metrics` for real KV-cache occupancy, context
  utilization, and prompt-cache hit rate instead of char-based
  estimates; add queue-wait-per-job and (once retrieval ships)
  retrieval-hit stats to `/diagnostics`. The measurement substrate
  every §7 item above should be judged by. `/metrics` polling and
  `retrieval_diagnostics()` shipped earlier (v0.87.6/v0.87.14); the
  remaining piece — `CognitionRunner.stats()`'s new `queue_wait_ms_
  p50`/`_p95` (distinct from `latency_ms_*`, which only measures time
  once a call is actually running) — closes this out. `/slots` itself
  was deliberately never polled (v0.87.6's own docstring: it can leak
  prompt content, unlike `/metrics`) — not a gap, a standing choice.

## 8. Explicit user-flagged ideas (2026-07-19) — not scoped, not started

Recorded verbatim-in-spirit per explicit user request ("add as an
action item for later") — none of this has been designed in detail,
scoped against existing machinery, or green-lit for implementation.
Filed the same way the vision doc's own deferred items are: tracked,
not forgotten, acted on only with future explicit direction.

- [ ] **Fine-tune the local model on Hearthmind's own generated data
  (LoRA/QLoRA).** `gemma-4-e2b-it` (or whatever `Config.llm_model`
  currently is) is a small general-purpose model; every prompt/
  response pair this project has ever sent it is already latent in
  `llm_prompt_stats`-adjacent telemetry but not durably stored for
  this purpose. Idea: persist a training corpus of real (prompt,
  completion) pairs generated during actual play, optionally paired
  with a stronger reference model's (Claude/GPT) completion for the
  *same* prompt as a quality target, then run a parameter-efficient
  fine-tune (LoRA/QLoRA — cheap enough to redo per-model-version)
  specifically toward Hearthmind's own prompt shapes (strict-JSON
  cognition/dialogue/belief schemas, this project's specific system
  prompts) rather than a generic instruction-tune. **Human-supervised
  curation** as the explicit quality gate: a reviewer inspects the
  top 5% (by some quality proxy — a reference model's own judged
  score, or downstream signal like "did this fallback ever trigger"),
  the worst 5% (to find and fix systematic failure modes, not just
  reward good answers), and a random 1% (an unbiased spot-check the
  other two bands can't provide) before any batch enters a training
  run — never a fully automated pipeline. Genuinely open questions
  before this could be scoped: where the corpus lives (a new SQLite
  table? a separate export?), retention/size, whether a "reference
  model" pass is itself worth its own cost, and how a fine-tuned
  checkpoint gets validated against a regression suite before
  replacing the live model. Ties into the whole "cognition
  infrastructure" theme of §7 but is a training-pipeline concern, not
  a runtime one — doesn't touch `SimulationEngine` at all.

- [ ] **NPC activity and environment reshape geography, further than
  today.** CLAUDE.md's own standing design priority already says
  "history should become physically visible; NPC activity should
  reshape the world over the long run," and `world/terrain_
  evolution.py` already has deforestation/reclaim mechanics — this is
  an explicit ask to go further: mining should visibly pit/scar hills
  over time (not just deplete an invisible `ResourceNode.amount`),
  sustained heavy settlement activity should measurably alter local
  terrain (worn paths already exist via `world/roads.py`; extend the
  same idea to quarrying, deforestation scars, riverbank erosion from
  traffic), and disasters/climate should interact with NPC-caused
  scarring (a mined-out hillside floods differently than an intact
  one). Pairs directly with §6's "spatial weather" and "soil
  fertility" items — same substrate, same R7 C++-first discipline —
  and with §5's ruins mode (a mined-out predecessor settlement's scars
  are exactly the kind of "findable" history that mode is designed to
  leave behind).

- [ ] **Expanded mineral/material economy — gold, iron, diamonds,
  silicon, etc. (Minecraft-like depth).** Today `ResourceKind.ORE`
  (`world/resources.py`) is a single undifferentiated mineral feeding
  `Settlement.materials` via the GATHER goal — real depth (distinct
  ore types with different rarity/biome affinity/tech-tier gating,
  feeding distinct crafted-good chains the way H4's tools/medicine
  supply chain already works) is unbuilt. The explicit framing given:
  **NPCs should believe they are living in a real world**, not a
  thin resource sim — richer materials existing, being sought after,
  fought over, and hoarded is in service of that belief, not just
  more numbers. Whatever shape this takes should extend the existing
  `ResourceGrid`/`Settlement.materials`/H4 supply-chain machinery
  (new `ResourceKind` values, new biome affinities, new crafted-good
  recipes) rather than building a parallel system — same "extend,
  don't duplicate" discipline as everything else in this doc. Also
  genuinely open: how deep the crafting tree should go before it
  competes with LLM-call budget for attention, and whether rarer
  materials should get their own belief/dispute/theft hooks (a
  diamond vein is a much more interesting thing to fight over than
  undifferentiated "materials").

## 9. Cultural depth & societal-evolution ideas (2026-07-19, explicit
   user request) — checklist only, not scoped, not started

Recorded per explicit user request ("scope these as checklist don't
implement yet"). Checked against the current code first, same
discipline as every other section — several of these turned out to be
partially or fully shipped already; marked accordingly rather than
re-listed as if missing.

- [ ] **Diversify cultural topics and rumors.** Partially covered
  today: `persistence/snapshot.py`'s `recent_events_diverse`/
  `_dedupe_rumor_topics` keep routine/duplicate rumor rows from
  crowding LLM prompts, and `Population.dialogue_topics` (§7,
  shipped) gives each PAIR a novelty ring nudging them off a repeated
  subject. Neither enforces genuinely concurrent SETTLEMENT-WIDE
  streams (economy/politics/families/religion/ecology/trade/
  festivals/crime/migration) an NPC chooses among — `narrative_
  direction.py` actively does the opposite (names 1-2 unifying
  themes quarterly). Would extend `dialogue_topics`' per-pair ring
  generalized to a settlement-wide category counter feeding
  `llm/dialogue.py`'s steering line, not a new subsystem.

- [ ] **Institutions get their own persistent memory.** Partially
  shipped, and clarifies what already exists rather than naming a
  gap: `Institution.beliefs` (`settlement/institutions.py`) already
  holds each institution's own belief list, kept in sync by `llm/
  beliefs.py`'s `sync_family_/council_/guild_beliefs` — but this is a
  FILTERED MIRROR of settlement-wide beliefs (resolves to that
  institution's members), not independently-generated institutional
  history. No institution has its own traditions/festivals/records
  list distinct from `Settlement.traditions`/`records`. Would extend
  `Institution.beliefs` + `Institution.objective` (§7, shipped) with
  an institution-scoped version of `llm/culture_digest.py`'s job.

- [ ] **Long-term reputation and family legacy.** Partially shipped —
  more exists than the ask implies, but the specific piece named
  (reputation surviving death) is confirmed genuinely absent:
  `Population._refresh_reputation` explicitly filters to `alive_ids`
  only, dropping a dead agent's reputation from the cache entirely.
  Real legacy machinery that DOES persist past death already: H7
  inheritance (goods/skill/bias/heir-memory/grudge), `Institution.
  feuds` (generational, outlives individual members), `memorials`,
  and `Settlement.records` (a notable villager's writings surviving
  them). Would extend the reputation cache's alive-only filter or add
  a records-consuming legacy-reputation term — not a new subsystem.

- [x] **Emotional/importance-based memory retrieval — already fully
  shipped**, v0.87.14. `Agent.retrieve_relevant_memories` scores every
  candidate memory by recency, salience, keyword-overlap relevance to
  the current situation, and a causal-link bonus, with its own
  `retrieval_diagnostics()` measuring hit rate — this was §7's
  "adaptive retrieval layer" item under a different name. No new work
  needed; flagged here only so it isn't re-proposed.

- [ ] **More cross-system interactions (politics/economy/religion/
  ecology/families).** Partially shipped, ad hoc rather than a general
  framework: laws feed disputes/theft penalties, schools feed
  invention chance (`education_invention_bonus`), tradition effects
  bias festival/harvest/grief/teaching mechanically
  (`culture.TRADITION_INFLUENCES`). No shared "cascade" abstraction
  exists to build a new interaction against — each existing example is
  its own small gate-then-mechanical-rider addition, and any new
  cross-link (the doc's own "tax -> guild unrest -> canceled festival
  -> folklore change" example) would be built the same ad hoc way,
  not as a new generic system.

- [x] **Prune/compress inactive relationships — already fully
  shipped.** `Population`'s relationship-decay path deletes an entry
  from `agent.relationships` once it decays to zero (the fix for a
  measured "~94 relationship entries per agent after only 5,000
  ticks" memory-leak finding, see docs/DECISIONS.md). This already
  solves the named O(N²) growth concern via decay-to-zero-then-delete;
  there is no separate "summarize but keep detail for significant
  ones" tier, but the underlying growth problem is not open. Flagged
  here only so it isn't re-proposed as missing.

- [ ] **Multi-layer culture** (village/family/guild/religion/
  neighborhood). Not shipped as layers — `Settlement.culture_digest`/
  `belief_digest` are single settlement-wide digests; `Institution.
  beliefs` (item 2 above) is a filtered subset of the same settlement
  list, not an independently-authored layer. Would extend `llm/
  culture_digest.py`'s job pattern, scoped per-institution, same
  shape as item 2's ask.

- [ ] **Competing narratives** (several major storylines coexisting).
  Partially covered by `dialogue_topics`' per-pair novelty and
  `recent_events_diverse`'s routine-category cap (item 1's
  machinery) — no settlement-wide "N storylines currently running"
  tracker exists. Would promote the same two existing mechanisms to
  settlement scope rather than building new tracking.

- [ ] **Geography as culture** (NPCs referencing named landmarks in
  conversation). Confirmed genuinely missing for dialogue
  specifically — `llm/geography.py` names river/lake features into
  `Settlement.place_names`, consumed today by `llm/chronicle.py`'s
  prompt, but a direct grep of `llm/dialogue.py` for `place_names`/
  geography finds zero matches; dialogue never references named
  terrain. Would extend `dialogue.build_prompt`'s existing optional-
  line pattern (same slot shape as its topic-novelty line) with a
  `Settlement.place_names` reference, zero new state needed.

- [ ] **Conversation grounded in simulation events.** Partially
  shipped — `dialogue.build_prompt` already carries lessons/mind/
  secrets/topics, and `recent_events_diverse` biases which events
  reach `town_brain`/`chronicle` prompts generally, but dialogue's own
  prompt does not currently pull a recent-objective-events slice the
  way `town_brain.py` does. Would pipe a filtered `recent_events_
  diverse` slice into `dialogue.build_prompt`, reusing the exact
  mechanism `town_brain` already consumes.

- [ ] **Long-term societal evolution across generations.** Largely
  already shipped under other names — traditions, folklore drift,
  dialect drift (v0.87.19), knowledge lifecycle (v0.87.15), laws/
  customs (v0.87.17), and ruins-mode successor worlds misreading old
  records (§5, "historical reinterpretation") all exist. What
  specifically remains open, if anything, needs a fresh audit against
  whichever concrete sub-behavior is meant beyond what's listed above
  — flagged as needing scoping, not assumed to be a real gap.

- [ ] **Investigate stalled era progression + gate it by infrastructure
  counts, not just a chance roll.** Confirmed genuinely missing, and
  the root cause of "civilization doesn't progress after 50,000
  ticks" is now understood, not just suspected: `era_for_tech_level`
  (`settlement/buildings.py`) gates era purely on `tech_level`, which
  is incremented ONLY by `llm/invention.py`'s rare seasonal roll
  (`INVENTION_CHANCE_PER_SEASON = 0.2`, itself gated on a currency/
  materials surplus + education bonus) — a dice roll with no
  infrastructure-count floor at all. A settlement can sit at
  `industrial` forever if the roll simply doesn't land, regardless of
  how many huts/roads/schools/carts it has built. Would extend `_maybe_
  schedule_invention`'s existing gate-then-roll pattern with concrete
  infra-count preconditions (a minimum count of standing HUTs/roads/
  SCHOOLs/carts before the NEXT era's threshold becomes reachable at
  all) alongside the currency/materials check already there — small,
  legible, era-by-era steps rather than a steep jump, matching the
  user's explicit framing ("many progression steps... each step to
  next era unlocks new buildings, infra and other options").

---

## Standing tests (unchanged, applied to all of the above)

1. Alive-even-if-unwatched? (§5 exists because the honest answer today
   is "yes, but nobody will ever know.")
2. Extends an existing store/job/pattern? Every item above names its
   host machinery; anything that can't shouldn't ship.
3. Bounded? Feud states, lexicons, prophecies, highlights, attention
   summaries — all capped lists or scalars.
4. Gated + fallback-covered? Every LLM-touching item degrades to
   "nothing happens," which is today's behavior.
5. Labels the supernatural? Never — the prophecy, observer-theology,
   and attention items are worded to live entirely inside Phase G's
   mundane-explanation rule.
