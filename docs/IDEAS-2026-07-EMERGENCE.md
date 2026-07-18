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

- [ ] **Directed intent: `SEEK_PERSON(target, intent)`.** One new goal
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

- [ ] **Deathbed release of secrets.** `Agent.secrets` currently dies
  with the agent. On a core-cast death with living kin colocated or
  nearby, a small chance the secret transfers — as a rumor seeded into
  the existing rumor machinery, attributed to the deathbed. Secrets
  then have a *lifecycle*: planted by Reflect()/disputes, guarded in
  dialogue, leaked at death, distorted by InterpretRumor(), condensed
  into folklore a generation later. Closes the loop on three shipped
  systems with ~no new state. Fallback: nothing happens (today's
  behavior).

- [ ] **Ceremonies agents attend: funerals and weddings.** Festivals
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

- [ ] **Deviance: a theft/taboo/justice loop.** Everyone is currently
  prosocial; the black-market *flag* exists but no agent ever wrongs
  another. Minimal version: a starving agent with low granary standing
  may take from a stocked granary or another agent's inventory
  (deterministic, need-gated, trait-gated by the existing axes); the
  act plants a secret on the taker and, if witnessed (colocation), a
  rumor on the witness. Council disputes gain a real caseload;
  dispute outcomes gain one new option beyond
  reconcile/feud/council_ruling: **restitution or ostracism** (a
  bounded standing penalty that gates SOCIALIZE targets and council
  eligibility, decaying over months). Deviance → gossip → reputation →
  justice → resentment is the classic emergence engine this world is
  missing, and every link already exists except the first and last.

- [ ] **Generational feuds between FAMILY institutions.** Feuds exist
  as pair-level dispute outcomes. Promote a repeated pattern (N feud
  outcomes across members of two families within a window —
  deterministic detection, same shape as the ritual detector) into an
  institution-level feud state, inherited by new members, softened by
  marriages across the line, hardened by deaths. Courtship across a
  feud line is then an emergent Romeo-and-Juliet the engine never
  scripted — it falls out of affinity mechanics colliding with the
  feud gate. Rides institution mirroring; capped like everything else.

- [ ] **Heritable temperament with mutation.** Inheritance covers
  goods/skill/bias; traits are rolled fresh. Blend child traits from
  parents ± noise and family *character* emerges over generations —
  "the stubborn Aldertons" becomes a real statistical fact the beliefs/
  folklore layer can then notice and name. One function, zero calls,
  and it makes deep time visible in people rather than buildings.

- [ ] **Migration by choice, not just fission.** Individuals never
  move between settlements. Push/pull rules from existing state
  (ostracized, feud pressure, starving while another settlement's
  granary is full, bonded partner lives there) let one agent relocate
  occasionally — carrying their memories, beliefs, and secrets into a
  population that doesn't share them. A migrant is an information
  vector: their arrival is how settlement A's folklore, rumors, and
  religion *actually spread* to settlement B, which currently only
  happens through the omen-echo backchannel.

## 2. Between settlements (a world, not parallel towns)

Multiple settlements exist (fission, cross-settlement relationships,
caravans, omen echoes) but they don't *want* anything from each other.

- [ ] **Letters carried by caravans.** Core-cast agents with a
  cross-settlement bond occasionally write a letter (one small LLM call
  or even template + memory splice); it travels at caravan speed and is
  delivered as a memory + possible rumor. Latency is the feature: a
  letter can arrive after its sender has died — the kind of moment
  observers screenshot. Rides caravan scheduling + records machinery.

- [ ] **Settlement-level stance (proto-diplomacy).** A per-pair
  settlement disposition scalar (bounded walk + event nudges — the
  temperament pattern, aimed outward) fed by trade balance, migrant
  treatment, feud spillover, disaster aid. Consumed as prompt bias for
  town brain / chronicle / caravan framing and one deterministic
  lever: caravan frequency. No war mechanic needed — coldness that an
  observer can trace to a decade-old grievance is more in-register
  than armies.

- [ ] **Refugees after disasters.** A settlement losing housing or
  granary below thresholds emits migrants toward the nearest viable
  settlement (reuses the migrant-arrival path from v0.85.x). The host's
  mood/beliefs react through existing channels. Disasters stop being
  local damage events and start rearranging the world's population —
  emergence from systems that all already exist.

- [ ] **Dialect drift.** Rare monthly-job rider: a settlement coins a
  term for a thing that dominated its recent events ("the white month"
  for a brutal winter), stored in a small capped lexicon, and
  subsequent prompts for *that settlement* are asked to prefer its
  lexicon. Two settlements descended from one fission slowly stop
  sounding alike; migrants and letters carry words across. Deep-time
  culture made audible in every LLM output for the price of one prompt
  line.

## 3. Closing meaning loops (belief that changes the world)

The rumor→folklore→religion→theme pipeline is shipped, but it's still
mostly *interpretive* — belief rarely feeds back into behavior.

- [ ] **Self-fulfilling prophecy.** Omens/dreams are retrospective by
  design. Add a stored, *vague* forward-looking line (rare; authored by
  the existing omen/dream jobs, e.g. "a hard reckoning before the
  second thaw") kept on the settlement with a confirmation window.
  Nothing in the engine ever makes it true — but while it's live, it's
  a prompt-bias line for cognition/town-brain (a fearful village
  stockpiles; a hopeful one builds), and the beliefs job later judges
  it confirmed/forgotten *from the subjective event record*. Belief
  nudging behavior which manufactures the confirming evidence is
  textbook emergence, fully inside the ambiguity discipline (the
  prophecy is only ever words; the "fulfillment" is the villagers'
  own doing).

- [ ] **The observer enters the theology.** `player_standing` and the
  player model exist, but the *villagers* have no concept of the hand
  that whispers and shifts weather. Let the religion/beliefs machinery
  occasionally attribute intervention-correlated events to a named
  something ("the Quiet Neighbor") — emerging only if the player
  actually intervenes, worded so it could equally be superstition.
  Players who meddle get mythologized by their own world; players who
  never touch anything never see it form. High surprise, zero new
  subsystems: it's one more belief subject.

- [ ] **Ask the Chronicler (on-demand, subjective).** An interface
  endpoint where the observer types a question and one LLM call answers
  **as the settlement's chronicler, from folklore + chronicle + beliefs
  + records only — never ground truth.** The answer can be wrong, and
  the observer can check it against the dev surface. This is the
  two-surface split turned into a *game*: the gap between what the
  world believes and what the world is becomes directly explorable.
  On-demand only, so it costs nothing unattended.

- [ ] **Subjective map mode.** A toggle that re-renders the observatory
  through the town's eyes: folk place-names instead of coordinates,
  buildings labeled by reputation ("the unlucky house"), map annotated
  with folklore sites, statistics replaced by the belief digest.
  Pure client work over data that already exists. The moment an
  observer flips it and sees the same world wearing its own myth is
  exactly the register this project aims for.

## 4. The watcher watched (Phase G, turned around)

- [ ] **Observer attention as a signal into the Town Consciousness.**
  The interface already knows what the observer does: which agent is
  inspected, which panels open, how long the tab stays connected.
  Fold a tiny bounded summary (attention counts, favorite agent, last
  seen) into the consciousness job's player model. Then the shipped
  intervention menu gains teeth it already owns: omens that cluster
  near the agent you watch most; a dream symbol seeded to *your*
  favorite; misplaced objects where you were looking yesterday. Every
  piece has a mundane explanation; only a returning observer would ever
  feel it. This is the single highest-surprise-per-line item on this
  list, and it is Phase G's thesis completed: the town isn't just a
  character — it has noticed *you*. Privacy note: all local, all
  in-save, document it plainly.

- [ ] **The consciousness keeps a grudge ledger about interventions.**
  Its memory exists; give whispers/weather-meddling a valence in it
  (helped during famine vs. toyed with during grief), so its
  intervention choices drift warm or cold toward the player across
  months. Player-legible only through pattern, never stated.

## 5. Making deep time legible (the always-on world's real problem)

An unattended world is mostly unwatched — the most interesting things
happen to nobody. These are observer-side, mostly zero-LLM.

- [ ] **"While you were away" digest.** DECISIONS.md itself flags
  "what happened while I was gone" as the interesting question. On
  client reconnect after a gap, one on-demand summary call (the
  summary tab machinery exists) over the event log since last-seen,
  written as the chronicler, headlined by deaths/births/feuds/omens of
  agents the observer previously inspected. Turns every return visit
  into an episode recap.

- [ ] **Anomaly/highlight log.** The metrics harness exists; nothing
  watches it. A cheap detector (rolling z-score per metric, plus
  hand-picked triggers: first religion, extinction near-miss, feud
  formation, belief flipping from true to false) appends to a bounded
  `highlights` list surfaced in the UI. The sim flags its own emergent
  moments so they stop being lost to an empty room. Also the honest
  test of the project's thesis: if the highlight log is boring, the
  emergence isn't real yet.

- [ ] **Year-reel export.** Snapshot keyframes + chronicle lines
  already exist; stitch a scrubbed year into a shareable replay
  (client-side canvas capture is enough). Observers evangelize worlds
  they can show.

- [ ] **Ruins mode / successor worlds.** On true extinction (or by
  choice), found a *new* world on the same map: terrain, ruins, roads,
  memorials persist; the old civilization's records/artifacts survive
  as findable text the new one's beliefs/folklore jobs may misread.
  Records machinery already writes exactly the right substrate. Deep
  time, archaeology, and "they got the old stories wrong" — maximum
  emergence per call, because the *content* was generated for free by a
  previous run.

- [ ] **Era-styled cartography.** The map's rendering style ages with
  the era system (rough hand-drawn early, surveyed lines later). Pure
  client polish that makes progress felt rather than read.

## 6. Substrate (small physical gaps that feed everything above)

- [ ] **Spatial weather.** Still uniform per-tick across the map
  (flagged in the 2026-07 review, unaddressed). Even a coarse 2–4 cell
  gradient gives geography consequences: the wet valley, the frost
  hollow, why settlement B's harvests differ — which the beliefs layer
  will then *theorize about*, rightly or wrongly. R7 territory,
  C++-first.

- [ ] **Soil fertility as a real field** (vision doc's own noted gap,
  still implicit in biome/farm state). Depletes under repeat farming,
  recovers fallow; makes rotation, ruin, and "the old fields" emerge.

- [ ] **Ambient audio keyed to hidden state.** Generative ambience
  (weather + daylight + a *mood/temperament-tinted* pad) in the client.
  The observer's ear notices the world darkening before their eye
  does — sensory foreshadowing of state the UI deliberately never
  labels. WebAudio, no assets, off by default.

## 7. Cognition infrastructure (the wishlist's real gaps)

The submitted wishlist is ~70% shipped (§0). What survives the audit
clusters around one theme: the mind machinery *stores* richly but
still *selects* context by fixed slices and digests, acts only on the
present tick, and remembers events as isolated strings. These items
fix that.

- [ ] **Adaptive retrieval layer.** Today every prompt is fixed
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

- [ ] **Causal memory links.** Memories are isolated strings; nothing
  records that the granary fire *caused* the hungry winter. At
  `_remember` call sites where the engine objectively knows the cause
  (disaster→damage, dispute→feud, death→grief), write an optional
  `because` tag pointing at the prior memory; let Reflect() author
  *subjective* — possibly wrong — causal links the same way ("the
  omen, then the flood"). Retrieval follows the chain (one hop), so an
  agent asked to decide about rebuilding recalls not just the fire but
  what it led to. Wrong causal links are a feature: superstition with
  mechanical substance.

- [ ] **Bounded episodic planning — ambitions get teeth.** `mind`
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

- [ ] **Emergent leadership.** COUNCIL is "living elders by age" — a
  clean rule, and a dead end for politics: influence can't be earned,
  contested, or lost. Weight seat selection by the existing
  `_prominence`/reputation aggregates (age as tiebreak), let a faction
  majority on the council bias dispute rulings and town-brain framing,
  and log seat changes as events the rumor/belief layer will chew on.
  A charismatic young founder displacing an elder — and the elder's
  family resenting it (§1 feuds) — is politics nobody scripted.

- [ ] **Per-agent voice.** Dialogue prompts carry traits and mind but
  no *manner of speaking*, so everyone samples from the same register.
  One line in `mind`, authored at the existing core-cast-entry genesis
  call (zero added calls): cadence, favorite figure of speech, verbal
  habit — drifting only when trait evolution (v0.87.0) fires. Garnish
  for dialogue/letters; the observer learns to recognize who's talking
  before reading the name. Pairs with §2 dialect drift (settlement
  lexicon + personal voice compose in the same prompt line).

- [ ] **Knowledge lifecycle: diffusion, loss, rediscovery.**
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

- [ ] **Laws, customs, taboos.** Council rulings resolve one dispute
  and evaporate; nothing accumulates into "how we do things here."
  Promote repeated same-kind rulings (deterministic detector, ritual
  pattern) into a small capped `customs` list with a mechanical rider
  from a fixed menu (culture-rider pattern: granary-first winters,
  no-building on memorial ground, restitution-over-ostracism). Taboo
  violations feed §1's deviance loop as aggravators. Settlements
  diverge in *law* the way they already diverge in belief — and
  migrants (§1) get to be foreigners who don't know the rules.

- [ ] **Institution objectives.** Institutions hold beliefs and
  dispositions but want nothing. One slow-revised objective line per
  institution (guild: secure materials; family: a council seat; the
  belief-system institution: a shrine in the new settlement), authored
  by the existing institution-belief job — consumed as prompt bias for
  members' cognition and dispute framing. Cross-institution objective
  collisions are faction politics arriving bottom-up.

- [ ] **Dialogue novelty memory.** The live-LLM path can still
  converge on the same topics pair after pair. Keep a tiny per-pair
  ring of the last N topics (subject strings already parsed from
  exchanges) and one prompt line: "you have lately talked about X, Y —
  find something new or go deeper." Cheap, bounded, measurable in the
  surfaced-conversation feed.

- [ ] **llama-server-side diagnostics.** v0.87.5's own flagged next
  step: poll `/slots`/`/metrics` for real KV-cache occupancy, context
  utilization, and prompt-cache hit rate instead of char-based
  estimates; add queue-wait-per-job and (once retrieval ships)
  retrieval-hit stats to `/diagnostics`. The measurement substrate
  every §7 item above should be judged by.

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
