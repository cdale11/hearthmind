"""Occupations: real professions NPCs take up, distinct from `skills`
(procedural teachable proficiency) and `Institution` membership (FAMILY/
COUNCIL/GUILD/FACTION). v0.87.44 jobs/economy batch (explicit live
request: "add proper jobs that npcs can take up and drive economy like
baker, builder, banker, teacher, priests, mayor, fisherman, farmer,
shopkeeper, businessman").

Deliberately deterministic, not LLM-authored: an occupation is assigned
to every mature agent (see `Population._maybe_assign_occupation`), so an
LLM call per assignment would violate the project's core-cast LLM-volume
budget (CLAUDE.md: "any new per-agent... LLM decision must be core-cast-
gated"). Assignment reads real settlement need (which occupations are
understaffed relative to population) rather than pure chance, so a town's
occupation mix stays roughly proportionate as it grows.

Each occupation's mechanical effect reuses an EXISTING presence-driven
building mechanic (the same shape WORKSHOP/SCHOOL/GRANARY already use)
rather than inventing ten bespoke systems: an on-occupation worker counts
as `OCCUPATION_STAFF_BONUS` workers instead of 1 at their matching
building's staff count, via `occupation_staff_weight`. This makes an
occupation a genuine productivity multiplier, not a cosmetic label,
while staying additive to (not a replacement for) the existing skills
system — a baker with high SKILL_FARMING... no, a baker's own craft
isn't a named skill; occupation and skill are deliberately orthogonal
axes (see docs/DECISIONS.md, "jobs/occupations" pass).
"""
from __future__ import annotations

from hearthmind.settlement.buildings import BuildingKind

OCCUPATION_BAKER = "baker"
OCCUPATION_BUILDER = "builder"
OCCUPATION_BANKER = "banker"
OCCUPATION_TEACHER = "teacher"
OCCUPATION_PRIEST = "priest"
OCCUPATION_MAYOR = "mayor"
OCCUPATION_FISHERMAN = "fisherman"
OCCUPATION_FARMER = "farmer"
OCCUPATION_SHOPKEEPER = "shopkeeper"
OCCUPATION_BUSINESSMAN = "businessman"
OCCUPATION_SURVEYOR = "surveyor"
"""v0.87.45 exploration batch (live request, same message as the
original ten: "expand-surveyor"): a roaming, not building-tied,
occupation — a surveyor's AgentGoal is forced to EXPLORE (see
`Population._dispatch_movement`), pathing toward the settlement's own
`Settlement.explored_tiles` frontier and recording findings rather than
producing at any fixed workplace. Absent from `OCCUPATION_WORKPLACES`
for exactly that reason."""

ALL_OCCUPATIONS: tuple[str, ...] = (
    OCCUPATION_BAKER, OCCUPATION_BUILDER, OCCUPATION_BANKER, OCCUPATION_TEACHER,
    OCCUPATION_PRIEST, OCCUPATION_MAYOR, OCCUPATION_FISHERMAN, OCCUPATION_FARMER,
    OCCUPATION_SHOPKEEPER, OCCUPATION_BUSINESSMAN, OCCUPATION_SURVEYOR,
)

OCCUPATION_WORKPLACES: dict[str, tuple[BuildingKind, ...]] = {
    OCCUPATION_BAKER: (BuildingKind.GRANARY,),
    OCCUPATION_TEACHER: (BuildingKind.SCHOOL, BuildingKind.UNIVERSITY),
    OCCUPATION_PRIEST: (BuildingKind.SHRINE,),
    OCCUPATION_FISHERMAN: (BuildingKind.HATCHERY,),
    OCCUPATION_BUSINESSMAN: (BuildingKind.WORKSHOP, BuildingKind.FACTORY, BuildingKind.DOCK, BuildingKind.OIL_RIG),
    OCCUPATION_BANKER: (BuildingKind.MARKET,),
    OCCUPATION_SHOPKEEPER: (BuildingKind.MARKET,),
}
"""Which BuildingKind(s) each occupation's staff-weighting bonus applies
at (see `occupation_staff_weight`). BUILDER (construction/repair sites,
not one BuildingKind), FARMER (farm plots, not a Building at all), and
MAYOR (settlement-wide, not site-specific) are deliberately absent —
each has its own dedicated hook instead, see their call sites in
`agents/population.py`."""

OCCUPATION_STAFF_BONUS = 1.5
"""An on-occupation worker at their matching workplace counts as this
many ordinary workers for that building's staff-scaled production (see
`occupation_staff_weight`) — a real, meaningful productivity edge (50%)
without letting one specialist alone outproduce a fully-staffed
generalist crew at MAX_WORKERS."""

BANKER_INCOME_PER_TICK = 0.025
"""A banker present at a standing MARKET generates currency directly —
distinct from SHOPKEEPER's caravan-trade-terms boost at the same
building (see `Population._maybe_run_market_workers`); financial work
(lending/managing the settlement's reserve) versus retail."""

SHOPKEEPER_CARAVAN_YIELD_BONUS = 0.15
"""Extra multiplier on caravan trade yield (stacks with `MARKET_
CARAVAN_YIELD_MULTIPLIER`) per shopkeeper present at a standing MARKET
when a caravan visits — a shopkeeper genuinely negotiates a better
trade, capped the same way RAFT/CART bonuses are (see `Population.
_maybe_schedule_caravan`'s caller in engine.py)."""

BUILDER_WORK_BONUS = 1.5
"""Same magnitude as OCCUPATION_STAFF_BONUS, applied directly to a
builder's own construction/repair contribution (see `Population.
_advance_construction`/`_maybe_repair`) rather than a staff-count
weighting, since those functions already iterate real per-worker
presence, not a simple headcount."""

FARMER_HARVEST_BONUS = 1.3
"""A farmer's own harvest yield multiplier (`Population._maybe_forage`'s
HARVEST_AMOUNT) — occupation-based, additive to (not a replacement for)
the existing SKILL_FARMING skill bonus."""

FISHERMAN_FORAGE_BONUS = 1.3
"""Same shape as FARMER_HARVEST_BONUS, for a fisherman's own wild-fish
catch (`Population._maybe_forage`'s FISH_HUNGER_RELIEF_MULTIPLIER
path) — occupation-based, on top of any HATCHERY staff-weighting."""

PRIEST_RITUAL_BOOST_MULTIPLIER = 1.25
"""A priest presiding over a SHRINE gathering (see `Population.hold_
festival`) deepens the relationship boost further — occupation-based,
stacks with the shrine's own flat `SHRINE_FESTIVAL_BOOST_MULTIPLIER`."""

MAYOR_REPUTATION_NUDGE = 0.01
"""A settlement with a living MAYOR gets a small, bounded boost to
`carrying_capacity`'s `coordination_term` governance-quality score
(see `Population.carrying_capacity`) — a mayor's presence is real
dedicated leadership on top of whatever the COUNCIL's own composition
already provides, not a single building's output."""


EXPLORATION_VISION_RADIUS = 3
"""How far around an agent's own tile counts as "explored" each tick
they're awake — small enough that covering genuinely new ground still
takes real sim-time (see `Population._mark_explored`), matching the
project's other radius-bounded scans (GATHER_SEARCH_RADIUS etc.)."""

EXPLORATION_FINDINGS_MAX = 60
"""Cap on `Settlement.exploration_findings`, same capped-list discipline
every other unbounded-growth-risk list in this project uses (omen_
history, priority_history, etc.)."""


def occupation_staff_weight(agent, occupation: str, awake_wellfed: bool) -> float:
    """How much one present, awake, well-fed agent counts toward a
    building's staff-scaled production this tick: `OCCUPATION_STAFF_
    BONUS` if their occupation matches the building's, else 1.0 (or 0.0
    if not awake/well-fed at all — callers already filter that, this
    just keeps the weighting math in one place)."""
    if not awake_wellfed:
        return 0.0
    return OCCUPATION_STAFF_BONUS if agent.occupation == occupation else 1.0
