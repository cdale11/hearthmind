"""Institutions: persistent entities that outlive the individuals who
belong to them (H3, docs/ROADMAP.md "Phase H" — explicit user directive
to introduce families/councils/guilds/markets/religions/politics as
first-class entities rather than leaving group identity implicit).

One lightweight `Institution` dataclass rather than a bespoke class per
kind, mirroring the July 2026 architecture review's Settlement-facade
split: a single shape now, specialized by `InstitutionKind` and reused
as the base for every future kind (councils, guilds, markets,
religions) instead of forcing a redesign each time a new kind is added.

v1 scope is deliberately narrow: only `FAMILY` institutions are formed,
and only automatically (a child's birth creates or extends one). Other
kinds, deliberate founding (an agent goal/LLM decision to start a
guild), and consumption beyond serialization/summary (dialogue/beliefs
referencing "the Hearth family", inheritance moving things through a
family on death) are explicitly future work — see docs/ROADMAP.md H3/H7.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class InstitutionKind(str, Enum):
    FAMILY = "family"
    # Future kinds (H3 follow-ups): COUNCIL, GUILD, MARKET, RELIGION.
    # Adding one is a matter of a new enum value plus a formation path
    # (mirroring _maybe_form_family) — the Institution shape below
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
    """Same shape as `Settlement.beliefs` entries — reserved for a
    future pass where an institution accumulates its own theories
    (H2's "world models" extended to institution-scoped holders),
    deliberately unpopulated by anything in this v1."""

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
