"""Districts: a collective-population layer above individually-
simulated agents (D6, docs/ROADMAP-2026-07-REMAINING.md — "social
scaling beyond several hundred/one thousand villagers," explicit user
directive: "at some number of villagers as threshold promote them to
collective NPCs instead of single NPCs... districts, smaller towns").

D6's diagnosed problem: every `Agent` carries an O(population) social
surface (the pairwise `Ledger` — relationships/trust/debts keyed by any
other agent's id) with no locality partition, realistic at a few
hundred, implausible at a thousand+. This is the actual fix, not a
performance-layer stopgap: once a settlement's individually-simulated,
non-core population crosses `DISTRICT_INDIVIDUAL_CAP`, the least-
prominent excess is genuinely REMOVED from individual simulation
(`Population.agents`/the AgentStore, and — critically — every other
living agent's `Ledger` entry for them) and folded into a `District`'s
aggregate population count instead. A collectivized person no longer
has a Ledger entry anyone can hold, which is what actually bounds the
social surface — a settlement of ten thousand does not give any single
agent ten thousand potential relationships, because past the cap the
excess simply isn't a Ledger participant anymore.

A District is deliberately NOT a named character or an Institution —
it has no beliefs, no cognition, no LLM authorship. It is closer to
`FarmGrid`/`WildlifeGrid`: an aggregate population figure ticked by
cheap deterministic math (`tick_district`), still a genuine part of the
settlement's economy (a small per-capita materials contribution) and
demography (its own birth/death accumulator), just not simulated one
person at a time. `DISTRICT_MAX_POPULATION` caps a single district
before a new one spins up (the "smaller towns" half of the directive —
a settlement doesn't grow one unbounded collective blob, it grows more
named wards, each independently tracked)."""
from __future__ import annotations

from dataclasses import dataclass


DISTRICT_INDIVIDUAL_CAP = 250
"""How many non-core-cast agents a settlement keeps individually
simulated (full `Agent`, full `Ledger` participation) before the excess
is collectivized into districts. Core-cast agents (`Population.
core_agent_ids`) are never collectivized regardless of count — see
`Population.core_agent_ids`'s own "LLM budget" framing in CLAUDE.md;
this is the same "named cast stays named" boundary applied to identity/
social-surface scaling rather than LLM call volume. Sized at the
project's own "several hundred" framing from D6's original diagnosis
(docs/ROADMAP-2026-07-REMAINING.md) — a settlement well under this
never collectivizes anyone, so small/typical worlds are completely
unaffected."""

DISTRICT_MAX_POPULATION = 150
"""A single district's population cap before a NEW district is founded
instead of growing the existing one further — the "smaller towns" half
of the directive. Deliberately smaller than `DISTRICT_INDIVIDUAL_CAP`
so a settlement's collectivized population reads as several named wards
rather than one undifferentiated mass once it's large enough to need
more than one."""

DISTRICT_BIRTH_RATE_PER_DAY = 0.00045
"""Expected daily births per collectivized resident at neutral hunger —
reasoned from `agents.agent.REPRODUCTION_CHANCE_PER_TICK` (0.01/tick,
an individually-simulated PAIR's roll, not a per-person daily rate) by
converting to a per-person daily order-of-magnitude via `Config.
minutes_per_day`/`sim_minutes_per_tick`'s typical ratio rather than
copying the individual roll verbatim — a district's births are
statistical, not a same-shape pairwise mechanic. Scaled by `(1.0 -
avg_hunger)` in `tick_district` so famine suppresses growth the same
directional way `REPRODUCTION_SETTLEMENT_HUNGER_CEILING` gates
individual reproduction. Re-tune from a live population-growth-rate
comparison against individually-simulated settlements of similar size
if districts visibly out- or under-grow their un-collectivized peers."""

DISTRICT_DEATH_RATE_PER_DAY = 0.00025
"""Baseline expected daily deaths per collectivized resident (old age +
ordinary misfortune) at neutral hunger, scaled up toward `DISTRICT_
STARVATION_DEATH_RATE_PER_DAY` as `avg_hunger` rises in `tick_district`
— mirrors individual simulation's own hunger-worsens-mortality shape
(`STARVATION_DEATH_CHANCE_PER_TICK` et al.) without copying its exact
per-tick roll."""

DISTRICT_STARVATION_DEATH_RATE_PER_DAY = 0.004
"""Expected daily deaths per collectivized resident at `avg_hunger ==
1.0` (fully starved) — `tick_district` linearly interpolates between
`DISTRICT_DEATH_RATE_PER_DAY` and this across `avg_hunger`'s 0..1
range, so a district genuinely can shrink to nothing under sustained
famine, the same real consequence individual starvation already has."""

DISTRICT_HUNGER_SMOOTHING = 0.05
"""How fast a district's own `avg_hunger` drifts toward the settlement's
current individually-simulated `Population.avg_hunger()` each day
(exponential smoothing, same shape `Settlement.temperament`'s bounded
random walk and `Agent.immune_strength`'s drift-toward-target already
use elsewhere in this codebase) — a documented simplification: a
district has no farms/foraging of its own to simulate, so it shares in
the settlement's broader circumstance rather than tracking independent
food logistics. Flagged as a scope trim in docs/ROADMAP-2026-07-
REMAINING.md's D6 entry, not silently assumed away."""

DISTRICT_MATERIALS_PER_CAPITA_PER_DAY = 0.02
"""A collectivized resident still does something with their day — a
small passive materials trickle into `Settlement.materials`, real but
deliberately much smaller than an individually-simulated agent's own
GATHER contribution (which involves goal-directed movement, tools,
skill) — a background-economy contribution, not a mechanical wash for
being abstracted away. Re-tune against a live economy reading if
districts visibly distort settlement material balance at scale."""

_WARD_NAMES = (
    "North Ward", "South Ward", "East Ward", "West Ward",
    "Millgate", "Riverside", "Hollow Row", "Coppergate",
    "Elmstead", "Foundry Quarter", "Backfields", "Longacre",
)
"""Fully procedural, zero-LLM-cost naming pool — same "geography naming
is fully procedural" precedent as `world/geography.py`'s settlement
place-names. Cycles with a numeric suffix once exhausted (see
`fallback_district_name`), so an arbitrarily large settlement never
runs out of distinct names."""


def fallback_district_name(ordinal: int) -> str:
    """`ordinal` is 0-indexed (this settlement's Nth district founded).
    Deterministic and collision-free by construction (each ordinal maps
    to exactly one name), matching every other fallback-naming
    convention in this codebase (e.g. `culture.fallback_tradition`)."""
    base = _WARD_NAMES[ordinal % len(_WARD_NAMES)]
    cycle = ordinal // len(_WARD_NAMES)
    return base if cycle == 0 else f"{base} {cycle + 1}"


@dataclass
class District:
    """One collectivized population pocket within a settlement. See
    module docstring for why this is deliberately NOT an `Institution`
    or a named character."""

    id: int
    settlement_id: int
    name: str
    population: int
    founding_tick: int
    avg_hunger: float = 0.0
    _birth_accumulator: float = 0.0
    _death_accumulator: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "settlement_id": self.settlement_id, "name": self.name,
            "population": self.population, "founding_tick": self.founding_tick,
            "avg_hunger": self.avg_hunger,
            "birth_accumulator": self._birth_accumulator,
            "death_accumulator": self._death_accumulator,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "District":
        return cls(
            id=data["id"], settlement_id=data["settlement_id"], name=data["name"],
            population=data["population"], founding_tick=data["founding_tick"],
            avg_hunger=data.get("avg_hunger", 0.0),
            _birth_accumulator=data.get("birth_accumulator", 0.0),
            _death_accumulator=data.get("death_accumulator", 0.0),
        )


def tick_district(district: District, settlement_avg_hunger: float) -> tuple[int, int]:
    """Advances one district by one day (called at `day_end` cadence,
    not per-tick — a district is demographic/economic background, not a
    moment-to-moment simulation). Returns `(births, deaths)` for this
    call, both usually 0 — same fractional-accumulator pattern as every
    other slow-statistical-process in this codebase (e.g. terrain
    evolution's roll-batches): the true expected rate is almost always
    less than 1 person/day, so a naive `round()` would silently floor
    every district to zero growth forever. Mutates `district` in
    place."""
    district.avg_hunger += (settlement_avg_hunger - district.avg_hunger) * DISTRICT_HUNGER_SMOOTHING
    if district.population <= 0:
        return 0, 0
    birth_rate = DISTRICT_BIRTH_RATE_PER_DAY * (1.0 - district.avg_hunger)
    death_rate = DISTRICT_DEATH_RATE_PER_DAY + (
        DISTRICT_STARVATION_DEATH_RATE_PER_DAY - DISTRICT_DEATH_RATE_PER_DAY
    ) * district.avg_hunger
    district._birth_accumulator += district.population * max(0.0, birth_rate)
    district._death_accumulator += district.population * max(0.0, death_rate)
    births = int(district._birth_accumulator)
    deaths = int(district._death_accumulator)
    district._birth_accumulator -= births
    district._death_accumulator -= deaths
    deaths = min(deaths, district.population)
    district.population += births - deaths
    return births, deaths
