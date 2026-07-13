"""A single inhabitant: position, needs, lifecycle, and relationships.

Milestone 2 scope: agents have needs that decay and a resting/awake state
that responds to them, and they wander the walkable terrain (slice 1).
Phase A closes the loop M2-2 left open: agents now forage
(hearthmind/world/resources.py), age, can die of starvation or old age,
and can build affinity with nearby agents that leads to reproduction (see
docs/DECISIONS.md, A1-A3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgentState(str, Enum):
    AWAKE = "awake"
    RESTING = "resting"


class AgentGoal(str, Enum):
    """A high-level intention set periodically (Phase B: once per sim-day,
    by the LLM cognition layer or its deterministic fallback) and executed
    deterministically every tick until re-evaluated. WANDER is both the
    default and the pre-Phase-B behavior, so agents with no goal set yet
    (or loaded from a pre-Phase-B save) behave exactly as before — see
    docs/DECISIONS.md, B2."""

    WANDER = "wander"
    FORAGE = "forage"
    SOCIALIZE = "socialize"
    REST = "rest"
    GATHER = "gather"
    """Added D8: collect building materials from forest/hills into the
    settlement's shared stockpile — see Population._maybe_gather."""


# Needs tuning. Kept as module constants rather than Config fields for now —
# these are behavioral parameters of the agent model itself, not world-shape
# parameters a deployer chooses at creation time. Revisit if that stops
# being true (e.g. once difficulty/pacing knobs are wanted).
HUNGER_RATE = 0.01
"""Hunger gained per tick, always (no food source yet to offset it)."""

ENERGY_DRAIN_AWAKE = 0.015
"""Energy lost per tick while awake (whether moving or not)."""

ENERGY_RECOVERY_RESTING = 0.06
"""Energy gained per tick while resting."""

REST_THRESHOLD = 0.2
"""Energy at or below which an awake agent falls asleep."""

WAKE_THRESHOLD = 0.85
"""Energy at or above which a resting agent wakes up."""

MOVE_CHANCE = 0.5
"""Per-tick probability an awake agent wanders to an adjacent tile."""

# --- Phase A: foraging, lifecycle, relationships ---------------------------

FORAGE_HUNGER_THRESHOLD = 0.4
"""Hunger at or above which an agent will forage if food is available —
regardless of awake/resting state, see docs/DECISIONS.md, D3."""

CRITICAL_HUNGER_THRESHOLD = 0.9
"""Hunger at or above which a resting agent wakes immediately, and a goal
of REST is overridden for the tick, so a starving agent isn't trapped
asleep while unable to reach food. Deliberately below
STARVATION_HUNGER_THRESHOLD (0.95) so the emergency wake fires before the
starvation-death countdown even begins. See docs/DECISIONS.md, D3."""

FORAGE_AMOUNT = 0.2
"""Units consumed from a resource node per successful forage attempt."""

FORAGE_HUNGER_RELIEF = 0.3
"""Hunger relief for a full (FORAGE_AMOUNT-sized) successful forage; scales
down proportionally if the node had less than FORAGE_AMOUNT remaining."""

MIN_LIFESPAN_TICKS = 20_000
MAX_LIFESPAN_TICKS = 40_000
"""Per-agent lifespan, assigned at spawn. An abstraction of "vitality"
rather than literal years — tunable, see docs/DECISIONS.md, A2."""

STARVATION_HUNGER_THRESHOLD = 0.95
STARVATION_TICKS_TO_DEATH = 200
"""Consecutive ticks at/above STARVATION_HUNGER_THRESHOLD before death."""

MATURITY_TICKS = 4_000
"""Age at which an agent becomes eligible to reproduce."""

RELATIONSHIP_GAIN_PER_TICK_COLOCATED = 0.02
RELATIONSHIP_DECAY_PER_TICK = 0.0005
"""Pulls a relationship value toward 0 (neither affinity nor rivalry)
from whichever side it's on — see Population._update_relationships.
Relationship values range -1..1 as of E2 (previously 0..1): a dialogue
exchange (see hearthmind/llm/dialogue.py) can now push a pair into
rivalry, not just toward friendship."""
REPRODUCTION_AFFINITY_THRESHOLD = 0.6
REPRODUCTION_CHANCE_PER_TICK = 0.01
"""Rolled only for mature, healthy, colocated pairs above the affinity
threshold — see Population._maybe_reproduce."""

REPRODUCTION_WELLFED_HUNGER = 0.35
"""The surplus gate's fallback arm: a pair with no personal food saved
can still have a child if both are clearly well-fed (hunger at or
below this — much stricter than _is_healthy's 0.7 ceiling). See
Population._maybe_reproduce and the July 2026 architecture review's
carrying-capacity rework: children follow surplus, so demography is
coupled to the food economy instead of only to a hard population cap.
Kept as an OR with the personal-food arm so a brand-new world (nobody
has saved food yet — the inventory skim needs farms/granaries to
exist first) can still grow off a good foraging stretch."""
RIVALRY_THRESHOLD = -0.4
"""Relationship value at or below which a pair is considered rivals for
prompt-context/diagnostic purposes — see hearthmind/llm/dialogue.py."""

DIALOGUE_COOLDOWN_TICKS = 300
"""Minimum ticks between two agents having another LLM-authored dialogue
exchange — keeps a stable pair that's colocated for a long stretch from
generating a new exchange (and LLM call) every tick. See
docs/DECISIONS.md, E2."""

TRIGGERED_COGNITION_COOLDOWN_TICKS = 200
"""Minimum ticks between two event-triggered (not staggered-daily)
cognition calls for the same agent — a hunger emergency or fresh grief
gets one immediate LLM re-reasoning, not one every tick for as long as
the condition persists. Shorter than DIALOGUE_COOLDOWN_TICKS since these
are individually rarer events, not a routine per-pair interaction. See
Population.due_for_triggered_cognition, docs/DECISIONS.md, "cognition
triggers beyond daily cadence" pass."""

DIALOGUE_SENTIMENT_DELTA = {"warm": 0.05, "tense": -0.05, "neutral": 0.0}
"""Relationship nudge applied when a dialogue exchange resolves, on top
of the passive per-tick colocation gain — the LLM's read on how the
exchange went, distinct from mere proximity. See
Population.apply_dialogue, docs/DECISIONS.md, E2."""

TRUST_DELTA = {"warm": 0.03, "tense": -0.04, "neutral": 0.0}
"""Agent.trust nudge applied alongside DIALOGUE_SENTIMENT_DELTA — smaller
magnitude and asymmetric (tense conversations cost more trust than warm
ones earn) since credibility is easier to lose than build, same
real-world asymmetry as reputation. Distinct axis from `relationships`:
see Agent.trust's docstring."""

TRUST_SKEPTICISM_THRESHOLD = -0.15
"""Below this, a rumor from that source is remembered with visible
skepticism instead of at face value — see Population.apply_dialogue."""

PERSONAL_FOOD_CAPACITY = 0.6
"""Max `Agent.inventory["food"]` — a small personal reserve, deliberately
far below granary/farm scale (GRANARY_CAPACITY 15.0), since this is one
person's pocket, not a storehouse. First slice of the "per-agent
inventory" gap CLAUDE.md flags as a real, genuinely large not-yet-built
item — scoped here to a single good (food) and direct agent-to-agent
transfer, not a full multi-good economy/market. See
docs/DECISIONS.md, "per-agent inventory and trade" pass."""

FORAGE_INVENTORY_SKIM = 0.05
"""Food stashed into `Agent.inventory["food"]` (capped at
PERSONAL_FOOD_CAPACITY) alongside a successful farm-harvest or
granary-withdrawal forage — deliberately not from wild foraging or an
emergency currency purchase, both of which are scarcity-driven with
nothing spare to set aside. See Population._maybe_forage."""

TRADE_FOOD_AMOUNT = 0.2
"""Personal food transferred in one barter exchange — matches
FORAGE_AMOUNT's scale. See Population._maybe_trade_food."""

TRADE_HUNGER_RELIEF = 0.25
"""Hunger relief for the receiving agent in a full trade — between a
wild forage (FORAGE_HUNGER_RELIEF 0.3) and a granary withdrawal
(GRANARY_HUNGER_RELIEF 0.4), since this is one neighbor's spare food,
not a communal store."""

TRADE_RELATIONSHIP_BOOST = 0.03
"""Relationship nudge for both parties when a trade completes — smaller
than DIALOGUE_SENTIMENT_DELTA's warm nudge (0.05): a material kindness,
not a conversation, but still a real bond-building act."""

TRADE_MIN_RELATIONSHIP = -0.2
"""An agent won't share personal food with someone at or below this
relationship value — rivals don't get fed first, though this is well
above RIVALRY_THRESHOLD (-0.4) so mere strangers (relationship 0) still
trade freely."""

TRAIT_SOCIABILITY_TRADE_THRESHOLD_SHIFT = 0.15
"""Integration milestone: a giver's own sociability shifts the
TRADE_MIN_RELATIONSHIP bar they personally apply, in
`Population._trade_relationship_threshold` (consumed by all three
barter functions — food/tools/medicine). A sociable giver shares with
even a mildly-disliked neighbor; an unsociable one holds out for a
closer bond than the settlement-wide default. Closes TRAIT_SOCIABILITY's
write-only loop the same way TRAIT_SOCIABILITY_CONTACT_CHANCE_INFLUENCE
does for teaching, just as a threshold shift rather than a chance
multiplier since trade here is deterministic-on-colocation, not a
per-tick roll."""

TRADE_TOOLS_AMOUNT = 1.0
"""H4: personal tools transferred in one barter exchange — see
Population._maybe_trade_tools. Chunkier than TRADE_FOOD_AMOUNT since
tools are a durable, lower-frequency good, not consumed on use."""

TRADE_MEDICINE_AMOUNT = 0.5
"""H4 extension: personal medicine transferred in one barter exchange —
see Population._maybe_trade_medicine. Between TRADE_FOOD_AMOUNT and
TRADE_TOOLS_AMOUNT in scale: medicine is consumed over a bout of
illness (not durable like tools), but a single dose is still a
meaningful share of MEDICINE_CAPACITY."""

GATHER_TOOLS_YIELD_BONUS = 0.4
"""H4: a GATHER-goal agent's own tools stretch what they bring back —
up to +40% materials per gather at a full personal tools stash
(TOOLS_CAPACITY), scaled linearly. Higher than SKILL_FARMING_YIELD_
BONUS (25%) since a physical tool is a more direct force-multiplier on
raw extraction than accumulated technique alone — the two are
deliberately distinct levers (skill from practice/teaching, tools from
the crafting supply chain) that could eventually stack for the same
goal. See Population._maybe_gather."""

ELDER_AGE_FRACTION = 0.8
ELDER_RECOVERY_MULTIPLIER = 0.7
"""Past ELDER_AGE_FRACTION of their own max_age_ticks, an agent's
resting energy recovery is multiplied by ELDER_RECOVERY_MULTIPLIER —
age-graded frailty, so an elder rests longer and does visibly less in
their final season instead of being indistinguishable from an adult
until the tick they die (death was a pure cliff at max_age_ticks; the
July 2026 architecture review flagged the missing decline). Recovery
rather than drain so a sheltered, cared-for elder still gets by —
they're slower, not doomed. See Population._update_needs."""

MAX_AGENT_MEMORIES = 8
"""Cap on Agent.memories — a short-term personal log (bond formed, rumor
heard, a bonded partner's death), not a full diary. Oldest entries drop
first. See docs/DECISIONS.md, relationship-memory pass."""

GRIEF_ENERGY_PENALTY = 0.2
"""Energy lost when a close bond (affinity >= REPRODUCTION_AFFINITY_THRESHOLD)
dies — grief has a real cost, not just a memory entry. See
Population._apply_deaths."""

INHERITANCE_SKILL_TRANSFER_FRACTION = 0.5
"""H7 (docs/ROADMAP.md "Phase H"): on death, an heir's skill closes half
the gap toward the deceased's — "a last lesson," not a full transfer
(skill is procedural; it can't simply be copied the way a possession
can, only accelerated by whatever notes/technique are left behind). A
no-op if the heir was already equally or more skilled. See
Population._apply_inheritance."""

INHERITANCE_BIAS_THRESHOLD = -0.3
INHERITANCE_BIAS_TRANSFER_FRACTION = 0.4
"""H7: a deceased agent's strong distrust of someone still living
(trust <= INHERITANCE_BIAS_THRESHOLD) partially carries over to their
heir — the heir's own trust in that person steps 40% of the way toward
the deceased's, a real "inherited grudge/bias" rather than pure
narration. Deliberately one-directional (only carries negative bias,
not positive trust) — a family's caution about someone is the more
mechanically interesting inheritance to model first; warm trust
already has its own accrual path through the heir's own dialogue."""

POPULATION_CAP = 400
"""A pure safety valve now, no longer the binding constraint it had
quietly become: the July 2026 architecture review measured every run
pinning at the old 200 indefinitely (food was post-scarce, so nothing
else ever pushed back). With the carrying-capacity rework — goal-gated
planting, crop rot (FARM_ROT_TICKS), and surplus-gated reproduction
(REPRODUCTION_WELLFED_HUNGER) — population is meant to be limited by
the food economy; this cap only guards against a pathological runaway.
Raised rather than removed so a tuning mistake in the new food loop
can't take the process down. See docs/DECISIONS.md, A2 and the
architecture-review implementation pass."""

OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK = 1e-7
"""Background per-agent-tick chance of a single spontaneous illness case
appearing (Population._maybe_outbreak rolls this once per tick, scaled by
current population and doubled by OUTBREAK_CROWDING_MULTIPLIER while the
settlement is crowded). At ~35,040 ticks/year (see time_system.py), this
is roughly 1 spontaneous case/year at population 200 uncrowded, versus
roughly 8/year at population 400 crowded — deliberately rare at low/mid
population and a real, felt pressure specifically where growth is
already straining housing. v0.44.0, "population control: disease" pass
— see docs/DECISIONS.md. The deterministic engine models the physical
fact of a pathogen taking hold; nothing here is LLM-judged, consistent
with disease being objective reality, not interpretation."""

OUTBREAK_CROWDING_MULTIPLIER = 6.0
"""Applied to OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK while the
settlement is crowded (same flag CROWDING_ENERGY_MULTIPLIER already
reads — population exceeding housing capacity) — real epidemiology:
crowd diseases originate and spread more readily in dense, under-housed
populations. Deliberately reuses the existing housing-pressure signal
rather than a second, disconnected density metric."""

OUTBREAK_ROAD_CONTACT_MULTIPLIER = 1.5
"""Integration milestone: scales OUTBREAK_BASE_CHANCE_PER_AGENT_PER_TICK
by `1.0 + (fraction of the population on an established road tile) *
this` — infrastructure that connects people for trade/teaching also
connects them for contagion. Deliberately smaller-magnitude than
OUTBREAK_CROWDING_MULTIPLIER (crowding is the dominant, well-tuned
driver; roads are a real but secondary contact-rate signal on top of
it, same "never dominant" discipline every cross-system nudge in this
project follows) — a settlement with 100% of its people on roads
this tick sees at most a 2.5x multiplier, versus crowding's flat 6x."""

SICKNESS_TRANSMISSION_CHANCE_PER_TICK = 0.01
"""Chance a sick agent infects a colocated healthy agent, per tick they
share a tile. Compounds with how often agents actually end up colocated
(constant colocation over a full SICKNESS_DURATION_TICKS bout would make
infection near-certain; real movement makes realized spread textured
rather than an instant sweep) — see Population._tick_disease."""

SICKNESS_DURATION_TICKS = 800
"""Ticks a bout of sickness lasts before natural recovery, absent death
— roughly 8 sim-days at the default pacing."""

SICKNESS_DEATH_CHANCE_PER_TICK = 0.0001
"""Per-tick chance of dying while sick, without a hospital — chosen so
the case-fatality rate over a full SICKNESS_DURATION_TICKS bout is
roughly 8% (0.0001 x 800 ticks), reduced by SICKNESS_HOSPITAL_KILL_
CHANCE_REDUCTION with a standing hospital and nudged by temperament
(TEMPERAMENT_KILL_CHANCE_INFLUENCE), same shape as predator-attack
lethality. A real, felt population check without being a devastating
plague — see docs/DECISIONS.md."""

SICKNESS_HOSPITAL_KILL_CHANCE_REDUCTION = 0.3
"""Fractional reduction to SICKNESS_DEATH_CHANCE_PER_TICK, settlement-
wide, once at least one hospital is standing — same magnitude and
rationale as HOSPITAL_KILL_CHANCE_REDUCTION for predator attacks: care
exists and measurably improves survival odds. Gives the town brain's
"health" priority (already mapped to HOSPITAL, see settlement/
buildings.py's _PRIORITY_TO_KIND) a mechanical reason to matter beyond
the rare no-hospital-yet-and-someone-died-to-a-predator fallback arm."""

SICKNESS_ENERGY_DRAIN_MULTIPLIER = 1.3
SICKNESS_HUNGER_RATE_MULTIPLIER = 1.2
"""A sick agent feels it mechanically, not just narratively — faster
energy loss and hunger accrual while unwell. Same "small nudge, real
consequence" magnitude as CROWDING_ENERGY_MULTIPLIER. See
Population._update_needs."""

IMMUNITY_DURATION_TICKS = 400
"""Disease v2 (docs/DECISIONS.md): ticks a just-recovered agent stays
resistant to reinfection — deliberately half of SICKNESS_DURATION_TICKS
(~4 sim-days), a real but temporary window rather than lifelong
immunity, matching how most real endemic illnesses work. Set on
Agent.immune_ticks at recovery; see Population._tick_disease for the
decay and Population._maybe_outbreak for the index-case exclusion."""

GOSSIP_OPINION_CONTAGION = 0.15
GOSSIP_OPINION_MAX_STEP = 0.05
"""When a rumor names a specific third villager, each listener's
opinion of that person relaxes toward the *speaker's* opinion by this
fraction (capped at MAX_STEP per rumor, and skipped entirely when the
listener doesn't trust the speaker — see TRUST_SKEPTICISM_THRESHOLD).
This is the mechanism that makes gossip a real social force: opinions
now propagate through the conversation graph instead of only through
direct contact, so a well-connected critic can sour a village on
someone they've barely met — and a skeptical village can't be swayed.
See Population.apply_dialogue, docs/DECISIONS.md, architecture-review
implementation pass (gossip contagion)."""

SKILL_FARMING = "farming"
"""The only named skill in H5 v1 — see `Agent.skills`. A single
dimension deliberately, not a skill tree: this is the smallest slice
that makes "knowledge spreads through teaching/observation/
apprenticeship" mechanically real (practiced yield bonus + colocated
teaching) without redesigning every profession-shaped goal at once."""

SKILL_PRACTICE_GAIN = 0.01
"""Proficiency gained per successful farm harvest by the harvester
themself — "observation"/learning-by-doing. Small: ~100 harvests to go
from 0 to full mastery, a genuine multi-season apprenticeship, not an
instant unlock."""

SKILL_TEACHING_CHANCE_PER_TICK = 0.02
SKILL_TEACHING_GAIN = 0.015
SKILL_TEACHING_MIN_GAP = 0.15
"""A colocated pair where one agent's farming proficiency is at least
SKILL_TEACHING_MIN_GAP above the other's has a small per-tick chance of
the more skilled one teaching — the learner's proficiency steps toward
the teacher's by SKILL_TEACHING_GAIN, same "small nudge, real
consequence, colocation-driven" shape as relationship gain and gossip
contagion above. Faster than solo practice (SKILL_PRACTICE_GAIN),
consistent with teaching being a genuinely faster way to learn than
trial and error alone."""

INSTITUTION_TEACHING_BONUS_MULTIPLIER = 1.4
"""Integration milestone: `Population._maybe_teach_skills`'s roll
chance is multiplied by this when teacher and learner share a living
FAMILY or COUNCIL institution — learning from your own household or
elders is more effective than a passing lesson from a stranger.
Deliberately smaller than the trait/culture multipliers can combine to
(a modest, legible bonus, not a dominant one), and stacks with both
rather than replacing either."""

SKILL_FARMING_YIELD_BONUS = 0.25
"""At full mastery (proficiency 1.0), a farming-skilled harvester gets
up to +25% hunger relief per harvest — see Population._maybe_forage.
Same order of magnitude as TECH_BONUS_PER_LEVEL's per-invention harvest
bonus (15%), deliberately a bit higher since this is a per-person
ceiling requiring real practice/apprenticeship time, not a one-off
settlement-wide unlock."""

SKILL_CONSTRUCTION = "construction"
"""H5 extension (docs/ROADMAP.md "Phase H"): the second skill, gained
by practice (`Population._advance_construction`) and colocated teaching
(`_maybe_teach_skills`, already skill-name-agnostic — see H5 v1's own
docstring). Boosts that worker's own contribution to a construction/
repair site's progress, the same "practiced yield bonus" shape
`SKILL_FARMING` already established, just at a different mechanic."""

SKILL_CONSTRUCTION_SPEED_BONUS = 0.25
"""Same magnitude as SKILL_FARMING_YIELD_BONUS — a fully-skilled crew
(average construction proficiency 1.0) builds/repairs up to 25% faster
than an unskilled one, on top of (not instead of) the existing
materials-multiplier and tech-level bonuses."""

SKILL_INVENTION_BONUS_WEIGHT = 0.3
"""H5 extension: the settlement-wide average of both skills (farming +
construction) gives a small additive nudge to invention chance
(`SimulationEngine._maybe_schedule_invention`), mirroring `education_
invention_bonus`'s shape (1.0 + something). This is the roadmap's own
suggested H5 evolution point ("tech_level becomes the settlement-
aggregate signal... rather than an independently-rolled scalar") taken
as an *additive nudge* rather than a full replacement of the existing
roll — the roll, prosperity gate, and education bonus are all
untouched; a skilled population invents somewhat more readily on top of
them, not instead of them. Deliberately smaller than education's
uncapped 1.0-per-education-level scale (this maxes out at +30% at full
average mastery across the whole population, a much narrower ceiling)
since two narrow skills are a much thinner signal of general
inventiveness than accumulated formal education."""

# --- H6: psychology — a compact, bounded personality vector ----------------

TRAIT_RESILIENCE = "resilience"
TRAIT_SOCIABILITY = "sociability"
"""The two v1 axes `Agent.traits` holds — deliberately not a big-five
system. Resilience: how well an agent copes with hardship/loss (low =
more fragile/shaken by trauma, high = hardy). Sociability: draw toward
social contact vs. solitude. Both -1..1, 0.0 = neutral/unformed."""

TRAIT_AMBITION = "ambition"
"""H6 extension (docs/ROADMAP.md "Phase H"): a third axis, drawn from
the roadmap's own "identity, values, ambition" list — how much an agent
is driven to build/achieve/master something vs. content with routine.
Same -1..1/0.0-neutral convention as the other two. Nudged up by
tangible achievement (founding a building, first reaching mastery in a
skill — see TRAIT_AMBITION_FOUNDING_NUDGE/TRAIT_AMBITION_MASTERY_NUDGE)
rather than by hardship/social contact like resilience/sociability —
ambition is earned, not suffered or given."""

TRAIT_STEP_MAX = 0.02
TRAIT_MEAN_REVERSION = 0.99
"""Monthly bounded-random-walk parameters — same shape as `Settlement.
temperament`'s `TEMPERAMENT_STEP_MAX`/`TEMPERAMENT_MEAN_REVERSION`,
reused at agent scale. Slower mean reversion than temperament's 0.97
(a person's underlying disposition should drift less readily than a
whole settlement's mood) and a smaller step, since 400 agents each
walking is a lot more individual variance to keep bounded and legible
than one settlement-wide number. See Population._tick_traits."""

TRAIT_GRIEF_NUDGE = -0.03
TRAIT_VIOLENCE_NUDGE = -0.05
TRAIT_SUSTAINED_HUNGER_NUDGE = -0.01
"""Event-driven resilience nudges — "nudged slowly by lived experience
(grief, violence witnessed, sustained hunger)," per docs/ROADMAP.md's
H6 evolution point verbatim. Violence (surviving/witnessing a predator
attack) hits harder than grief; sustained hunger is the mildest and
only applied while an agent is already critically hungry, mirroring
how starvation itself escalates gradually rather than snapping the
first tick. All three only ever push resilience down — recovery comes
from the monthly mean-reverting walk, the same way temperament recovers
from a bad season without a matching "good event" for every bad one."""

TRAIT_SOCIAL_CONTACT_NUDGE = 0.015
"""Sociability nudge on a positive social exchange (a completed trade —
food or tools) — small and positive, the mirror of the resilience
nudges above but the only trait axis with a routine upward pull, since
ordinary friendly contact is common and grief/violence are not."""

MASTERY_THRESHOLD = 0.95
"""A skill counts as "mastered" at or above this proficiency — the
trigger for TRAIT_AMBITION_MASTERY_NUDGE (see Population._maybe_forage/
_advance_construction, both of which check the practice-gain crossed
this threshold rather than firing every tick a mastered agent happens
to practice again)."""

TRAIT_AMBITION_FOUNDING_NUDGE = 0.04
TRAIT_AMBITION_MASTERY_NUDGE = 0.06
"""Ambition nudges on tangible achievement — founding a building
(`Population._maybe_start_construction`) or a skill first crossing
MASTERY_THRESHOLD through practice. Both larger than the resilience/
sociability event nudges: these are rarer, more deliberate
accomplishments, not routine lived experience, so they should register
more per occurrence even though they fire less often."""

TRAIT_NOTABLE_THRESHOLD = 0.3
"""A trait is only mentioned in cognition/dialogue prompts once its
magnitude clears this bar — same "only mentioned once notably warm/
cold" treatment `player_standing` already gets, so a freshly-neutral
agent's prompt isn't cluttered with "not particularly resilient or
fragile" noise."""

# --- integration milestone: traits become mechanically consumed, not write-only ---

TRAIT_RESILIENCE_DEATH_CHANCE_INFLUENCE = 0.25
"""How far personal `TRAIT_RESILIENCE` (-1..1) can push an agent's own
disease/predator death-chance roll away from the settlement-wide
baseline (`Population._tick_disease`/`_maybe_predator_attack`) — a
fully resilient agent's chance is scaled toward `1 - this`, a fully
fragile one toward `1 + this`. Previously traits were nudged by these
exact events (grief, violence, sustained hunger) but never read back by
any deterministic mechanic — this closes that loop: living through a
brush with danger measurably makes the next one a little more
survivable, or not, depending on how it went. Same small, symmetric,
never-dominant magnitude as TEMPERAMENT_KILL_CHANCE_INFLUENCE."""

TRAIT_RESILIENCE_STARVATION_TOLERANCE_INFLUENCE = 0.2
"""Fractional stretch/shrink on `STARVATION_TICKS_TO_DEATH` from
personal resilience (`Population._apply_deaths`) — a resilient agent
holds on somewhat longer into a hunger crisis, a fragile one somewhat
less. Same magnitude class as the death-chance influence above."""

TRAIT_SOCIABILITY_CONTACT_CHANCE_INFLUENCE = 0.3
"""Fractional nudge on personal trade-initiation and skill-teaching
roll chances from `TRAIT_SOCIABILITY` (-1..1) — a sociable agent reaches
out more readily, an unsociable one less. Consumed in
`Population._maybe_trade_food/_maybe_trade_tools/_maybe_trade_medicine`
and `_maybe_teach_skills`. Larger than the death-chance influence above
since these are routine, low-stakes rolls rather than life-or-death
ones — a bigger swing here is still never dominant (contact still
requires colocation + the base roll to begin with)."""

TRAIT_AMBITION_FOUNDER_SELECTION_WEIGHT = 0.4
"""How strongly `TRAIT_AMBITION` (-1..1) weights which eligible,
colocated agent personally owns a newly-founded HUT
(`Population._maybe_start_construction`), when more than one candidate
qualifies — an ambitious agent is more likely to be the one who steps
up and claims it, not guaranteed to be (still an RNG-weighted pick, not
a hard rule). Deliberately scoped to HUT ownership only, not council
seating — COUNCIL stays a clean, single-purpose "elders by age" rule
(`_maybe_form_council`/`_maybe_refresh_council`); mixing ambition into
that selection would blur what "a council of elders" means. Read side
of the same trait `TRAIT_AMBITION_FOUNDING_NUDGE` already writes to on
the event itself, closing that loop the same way resilience/
sociability close theirs."""


def describe_traits(traits: dict) -> str:
    """Shared by llm/cognition.py and llm/dialogue.py: a short natural-
    language fragment for whichever traits currently clear
    TRAIT_NOTABLE_THRESHOLD, or "" if none do. One function so both
    prompts describe personality the same way rather than drifting."""
    bits = []
    resilience = traits.get(TRAIT_RESILIENCE, 0.0)
    if resilience >= TRAIT_NOTABLE_THRESHOLD:
        bits.append("resilient, taking hardship in stride")
    elif resilience <= -TRAIT_NOTABLE_THRESHOLD:
        bits.append("shaken easily by hardship")
    sociability = traits.get(TRAIT_SOCIABILITY, 0.0)
    if sociability >= TRAIT_NOTABLE_THRESHOLD:
        bits.append("drawn to company")
    elif sociability <= -TRAIT_NOTABLE_THRESHOLD:
        bits.append("keeps to themself")
    ambition = traits.get(TRAIT_AMBITION, 0.0)
    if ambition >= TRAIT_NOTABLE_THRESHOLD:
        bits.append("driven to build and achieve")
    elif ambition <= -TRAIT_NOTABLE_THRESHOLD:
        bits.append("content with routine")
    return ", ".join(bits)


@dataclass
class Agent:
    id: int
    name: str
    x: int
    y: int
    hunger: float = 0.0
    energy: float = 1.0
    state: AgentState = AgentState.AWAKE
    age_ticks: int = 0
    max_age_ticks: int = MAX_LIFESPAN_TICKS
    starving_ticks: int = 0
    sick_ticks: int = 0
    """0 = healthy. >0 = ticks spent in the current bout of illness so
    far (governs recovery via SICKNESS_DURATION_TICKS and is reset to 0
    on recovery or death) — see Population._maybe_outbreak/_tick_disease.
    See docs/DECISIONS.md, "population control: disease" pass."""
    immune_ticks: int = 0
    """v2 of disease (v1 deliberately shipped with no immunity/
    reinfection modeling, flagged "extend later if wanted" —
    docs/DECISIONS.md): set to IMMUNITY_DURATION_TICKS on recovery,
    decremented every tick regardless of sick_ticks. While >0, this
    agent can neither become a fresh outbreak's index case nor catch
    the illness from a colocated carrier (Population._maybe_outbreak/
    _tick_disease) — temporary, not permanent, resistance, same
    "real but eventually fades" shape real post-infection immunity
    takes, not a one-time-only vaccine."""
    relationships: dict[int, float] = field(default_factory=dict)
    trust: dict[int, float] = field(default_factory=dict)
    """-1..1 per source agent id — a distinct axis from `relationships`
    (fondness): how much *credibility* this agent gives another's word,
    not how much they like them. Nudged alongside relationships on
    dialogue (see Population.apply_dialogue's TRUST_DELTA), but tracked
    separately so the two can diverge — someone can be well-liked but
    known to embellish, or a rival whose information has still proven
    reliable. Consumed by apply_dialogue when a rumor arrives: low trust
    in the speaker gets remembered with visible skepticism instead of
    at face value. The "discrete trust lever" flagged as a real, not-yet-
    built gap in CLAUDE.md's per-person-beliefs section. See
    docs/DECISIONS.md, "trust lever" pass."""
    inventory: dict[str, float] = field(default_factory=dict)
    """Personal possessions, currently just `{"food": 0.0..PERSONAL_FOOD_
    CAPACITY}` — stashed on a successful farm/granary forage (see
    FORAGE_INVENTORY_SKIM) and spent either on the agent's own future
    hunger or given to a colocated, non-rival neighbor in
    Population._maybe_trade_food. Distinct from `Settlement.materials`/
    `currency` (communal) and from granary `stored_food` (also
    communal) — this is the one thing that's unambiguously *this
    agent's own*. See docs/DECISIONS.md, "per-agent inventory and
    trade" pass."""
    parents: tuple[int, int] | None = None
    goal: AgentGoal = AgentGoal.WANDER
    goal_reason: str = ""
    memories: list[str] = field(default_factory=list)
    """Short personal log, capped at MAX_AGENT_MEMORIES — bonds formed,
    rivalries, rumors heard, a bonded partner's death. Fed back into this
    agent's own cognition prompt (see hearthmind/llm/cognition.py), so an
    agent's own history can shape its next goal. See docs/DECISIONS.md,
    relationship-memory pass."""
    skills: dict[str, float] = field(default_factory=dict)
    """H5 (docs/ROADMAP.md "Phase H"): procedural, teachable know-how —
    named skill -> proficiency (0..1) — deliberately separate from
    `Settlement.beliefs`/`Agent.memories`. A belief is interpretive and
    revisable ("the harvest failed because the town is unlucky");
    knowledge here is procedural and either applied correctly or not
    ("how to work a farm plot"). v1 has exactly one skill, `"farming"`
    (SKILL_FARMING), gained slowly through an agent's own practice
    (harvesting) and spread faster between colocated agents through
    teaching — see Population._maybe_forage/_maybe_teach_skills."""
    traits: dict[str, float] = field(default_factory=dict)
    """H6 (docs/ROADMAP.md "Phase H"): a compact, bounded (-1..1)
    personality vector — `TRAIT_RESILIENCE` and `TRAIT_SOCIABILITY` in
    v1, deliberately two axes, not a big-five system. Absent keys read
    as 0.0 (neutral), same convention as `relationships`/`trust`.
    Nudged slowly by lived experience (grief, violence witnessed,
    sustained hunger, positive social contact — see Population.
    _nudge_trait/_tick_traits) using the same bounded-random-walk-plus-
    event-nudge shape `Settlement.temperament`/`player_standing`
    already establish at the settlement level, reused here at agent
    scale rather than inventing a new one. Read into cognition/dialogue
    prompts as context once a trait is notable (see llm/cognition.py,
    llm/dialogue.py), the same "only mentioned once notably warm/cold"
    treatment temperament gets."""
    beliefs: list[dict] = field(default_factory=list)
    """H2 extension (docs/ROADMAP.md "Phase H" stage 2): this agent's
    own private, evolving theories about their life — same shape as
    `Settlement.beliefs` entries (subject/belief/confidence/formed_
    tick/revised_tick/revision_count/history), capped at llm/beliefs.
    MAX_PERSONAL_BELIEFS, formed/revised from this agent's own
    `memories` by a monthly LLM job
    (`SimulationEngine._maybe_schedule_personal_belief`) rather than
    settlement-wide events. Deliberately reuses the exact belief-entry
    shape and the generic (Settlement-independent) `llm.beliefs.
    parse_belief`/`push_belief_history`/`find_belief_index_by_subject`
    functions rather than inventing a parallel per-agent mechanism."""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "hunger": round(self.hunger, 4),
            "energy": round(self.energy, 4),
            "state": self.state.value,
            "age_ticks": self.age_ticks,
            "max_age_ticks": self.max_age_ticks,
            "starving_ticks": self.starving_ticks,
            "sick_ticks": self.sick_ticks,
            "immune_ticks": self.immune_ticks,
            "relationships": {str(k): round(v, 4) for k, v in self.relationships.items()},
            "trust": {str(k): round(v, 4) for k, v in self.trust.items()},
            "inventory": {k: round(v, 4) for k, v in self.inventory.items()},
            "parents": list(self.parents) if self.parents is not None else None,
            "goal": self.goal.value,
            "goal_reason": self.goal_reason,
            "memories": list(self.memories),
            "skills": {k: round(v, 4) for k, v in self.skills.items()},
            "traits": {k: round(v, 4) for k, v in self.traits.items()},
            "beliefs": list(self.beliefs),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Agent":
        parents = data.get("parents")
        return cls(
            id=data["id"],
            name=data["name"],
            x=data["x"],
            y=data["y"],
            hunger=data["hunger"],
            energy=data["energy"],
            state=AgentState(data["state"]),
            age_ticks=data.get("age_ticks", 0),
            max_age_ticks=data.get("max_age_ticks", MAX_LIFESPAN_TICKS),
            starving_ticks=data.get("starving_ticks", 0),
            sick_ticks=data.get("sick_ticks", 0),
            immune_ticks=data.get("immune_ticks", 0),
            relationships={int(k): v for k, v in data.get("relationships", {}).items()},
            trust={int(k): v for k, v in data.get("trust", {}).items()},
            inventory=dict(data.get("inventory", {})),
            parents=tuple(parents) if parents is not None else None,
            goal=AgentGoal(data.get("goal", AgentGoal.WANDER.value)),
            goal_reason=data.get("goal_reason", ""),
            memories=list(data.get("memories", [])),
            skills=dict(data.get("skills", {})),
            traits=dict(data.get("traits", {})),
            beliefs=list(data.get("beliefs", [])),
        )
