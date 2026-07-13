"""Institutions: persistent entities that outlive the individuals who
belong to them (H3, docs/ROADMAP.md "Phase H" — explicit user directive
to introduce families/councils/guilds/markets/religions/politics as
first-class entities rather than leaving group identity implicit).

One lightweight `Institution` dataclass rather than a bespoke class per
kind, mirroring the July 2026 architecture review's Settlement-facade
split: a single shape now, specialized by `InstitutionKind` and reused
as the base for every future kind (councils, guilds, markets,
religions) instead of forcing a redesign each time a new kind is added.

v1 scope was deliberately narrow: only `FAMILY` institutions, formed
automatically (a child's birth creates or extends one). H3 extension
(docs/ROADMAP.md "Phase H") adds a second kind, `COUNCIL` — formed once
a named settlement's population crosses a threshold, membership the
settlement's elders at that moment, still fully automatic (no agent
goal/LLM decision to found one). The integration milestone (docs/
DECISIONS.md) gave COUNCIL real mechanical agency where it previously
had none: `Population._maybe_refresh_council` keeps its *living*
membership topped up as members die (it used to silently decay into a
roster of the dead), `llm/beliefs.sync_council_beliefs` gives it its own
accumulated civic theories, and `Population.council_disposition` feeds
its members' average traits into both `town_brain`'s prompt/fallback
tie-break and `Population.carrying_capacity`'s coordination term. A
third kind, `GUILD` (v0.60.0, docs/DECISIONS.md "continue expanding"),
forms automatically once enough agents master a trade — see
`InstitutionKind.GUILD`'s docstring. All three kinds remain fully
automatic; deliberate founding (an agent choosing to start one) remains
future work — see docs/ROADMAP.md H3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InstitutionKind(str, Enum):
    FAMILY = "family"
    COUNCIL = "council"
    GUILD = "guild"
    """A third kind (v0.60.0, docs/DECISIONS.md "continue expanding"
    pass): unlike FAMILY/COUNCIL, GUILD is trade-specific — one GUILD
    instance per mastered skill (SKILL_FARMING/SKILL_CONSTRUCTION),
    `Institution.name` holding which skill (the first real consumer of
    that previously-always-empty field). Formed once enough living
    agents have mastered the same trade (`Population._maybe_form_
    guild`), membership grows as more agents reach mastery
    (`_maybe_refresh_guild`), and shared guild membership gives a
    teaching bonus specific to that one trade (`GUILD_TEACHING_
    BONUS_MULTIPLIER`), on top of — not instead of — the trade-
    agnostic FAMILY/COUNCIL bonus `_maybe_teach_skills` already
    applies."""
    # Future kinds: MARKET (the institution, distinct from BuildingKind.
    # MARKET the building), RELIGION. Adding one is a matter of a new
    # enum value plus a formation path — the Institution shape below
    # already supports any of them.


@dataclass
class Institution:
    """A persistent entity — currently only families — that a
    settlement's population organizes into. Deliberately shaped like
    `Settlement.beliefs`'s list-of-dicts pattern in miniature: a small
    struct plus its own `beliefs` list (the institution's persistent
    positions/norms, e.g. a family's accumulated theory about itself),
    rather than a heavyweight new subsystem. `member_agent_ids` is
    every agent who *ever* belonged, never pruned on death — the whole
    point of an institution is that it outlives its members (H7
    inheritance's future anchor point)."""

    id: int
    kind: InstitutionKind
    founding_tick: int
    member_agent_ids: set[int] = field(default_factory=set)
    name: str = ""
    """Freeform label — empty for now (families aren't currently named;
    a future pass could derive one, e.g. from a founding pair's names,
    once naming matters to a consumer)."""
    beliefs: list[dict] = field(default_factory=list)
    """Same shape as `Settlement.beliefs` entries — an institution's own
    curated slice of the settlement's evolving theories (capped at
    INSTITUTION_BELIEF_CAP, see llm/beliefs.py). Populated by
    `sync_family_beliefs` for FAMILY (settlement beliefs that resolve to
    a member's household) and `sync_council_beliefs` for COUNCIL
    (settlement beliefs that don't resolve to any person/family — a
    council's business is civic theories, not household gossip).
    Consumed by dialogue (family) and town_brain (council) — see
    `llm/town_brain.build_prompt`'s `council_beliefs` param."""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "founding_tick": self.founding_tick,
            "member_agent_ids": sorted(self.member_agent_ids),
            "name": self.name,
            "beliefs": list(self.beliefs),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Institution":
        return cls(
            id=data["id"],
            kind=InstitutionKind(data.get("kind", InstitutionKind.FAMILY.value)),
            founding_tick=data.get("founding_tick", 0),
            member_agent_ids=set(data.get("member_agent_ids", [])),
            name=data.get("name", ""),
            beliefs=list(data.get("beliefs", [])),
        )
