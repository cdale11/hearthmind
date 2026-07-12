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

MAX_AGENT_MEMORIES = 8
"""Cap on Agent.memories — a short-term personal log (bond formed, rumor
heard, a bonded partner's death), not a full diary. Oldest entries drop
first. See docs/DECISIONS.md, relationship-memory pass."""

GRIEF_ENERGY_PENALTY = 0.2
"""Energy lost when a close bond (affinity >= REPRODUCTION_AFFINITY_THRESHOLD)
dies — grief has a real cost, not just a memory entry. See
Population._apply_deaths."""

POPULATION_CAP = 200
"""Safety valve against unbounded growth before food scarcity/economy
naturally cap population; see docs/DECISIONS.md, A2."""


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
            "relationships": {str(k): round(v, 4) for k, v in self.relationships.items()},
            "trust": {str(k): round(v, 4) for k, v in self.trust.items()},
            "inventory": {k: round(v, 4) for k, v in self.inventory.items()},
            "parents": list(self.parents) if self.parents is not None else None,
            "goal": self.goal.value,
            "goal_reason": self.goal_reason,
            "memories": list(self.memories),
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
            relationships={int(k): v for k, v in data.get("relationships", {}).items()},
            trust={int(k): v for k, v in data.get("trust", {}).items()},
            inventory=dict(data.get("inventory", {})),
            parents=tuple(parents) if parents is not None else None,
            goal=AgentGoal(data.get("goal", AgentGoal.WANDER.value)),
            goal_reason=data.get("goal_reason", ""),
            memories=list(data.get("memories", [])),
        )
