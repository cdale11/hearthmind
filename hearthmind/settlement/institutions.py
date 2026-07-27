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
    FACTION = "faction"
    """Phase L (v0.80.0, docs/VISION-2026-07.md "Society & Power"): a
    cluster of living agents detected via mutual-trust-graph clustering
    (`Population._detect_faction_candidate`) — chosen loyalty rather
    than FAMILY's blood or GUILD's shared trade. Formed only once a
    cluster crosses a size/cohesion threshold; `Institution.name` holds
    the LLM-authored (or deterministic-fallback) name a faction is known
    by. Unlike GUILD, membership doesn't auto-grow as trust shifts — a
    faction's roster is fixed at formation, same "one-time-authored,
    persists as-is" shape as FAMILY.
    # Future kinds: MARKET (the institution, distinct from BuildingKind.
    # MARKET the building), RELIGION (Phase M). Adding one is a matter
    # of a new enum value plus a formation path — the Institution shape
    # below already supports any of them.
    """


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
    objective: str = ""
    """v0.87.12, "institution objectives" (docs/IDEAS-2026-07-EMERGENCE.
    md §7): one slow-revised line of what this institution WANTS (a
    guild securing materials, a family angling for a council seat, a
    council keeping the peace) — institutions previously held beliefs/
    dispositions but wanted nothing. Authored/revised by the existing
    monthly `_maybe_schedule_institution_belief` job (`llm/beliefs.py`'s
    `INSTITUTION_SYSTEM_PROMPT` widened with one optional field, zero
    added LLM call volume) — only overwritten when the model actually
    supplies a new one (empty answers leave the prior objective
    unchanged, same "retained across a fallback stretch" discipline
    every other digest field in this project follows). Consumed as
    prompt bias for members' cognition/dialogue and dispute framing —
    cross-institution objective collisions (two families both angling
    for the same council seat) are faction politics arriving
    bottom-up, never scripted."""
    culture_digest: str = ""
    """§9 "institutions get their own persistent memory" + "multi-layer
    culture" (docs/IDEAS-2026-07-EMERGENCE.md): one short, INDEPENDENTLY-
    AUTHORED sentence capturing this specific institution's own
    character, distinct from `beliefs` (a filtered mirror of settlement-
    wide beliefs, see that field's docstring) and from `Settlement.
    culture_digest` (the whole village's shape). Written by `llm/
    institution_culture.py`'s round-robin quarterly job
    (`SimulationEngine._maybe_schedule_institution_culture`) — one call
    per season for the whole world, flat regardless of institution
    count, same "spend the call only once real material exists"
    (beliefs/objective/feud history) discipline as `culture_digest`'s
    own fallback. Never fabricated: a genuine no-op fallback retains
    the prior digest across a flaky stretch."""
    objective_ticks_unmet: int = 0
    """Vision doc item 2.2 ("institutions with persistent goals that
    act"), docs/VISION-2026-07-22-LIVINGTERRARIUM.md: how many
    consecutive times `compute_objective` has re-derived the SAME want
    for this institution — a persistent, unmet objective, not a fresh
    one. Incremented/reset in `SimulationEngine._maybe_schedule_
    institution_belief` right where `objective` itself is recomputed;
    zero cost (reuses that job's existing monthly cadence, no new LLM
    call). Read by `_maybe_schedule_rule_proposal` — an institution
    stuck wanting the same thing long enough grounds the village's next
    self-authored rule proposal in that specific frustration ("the
    council that remembers a famine legislating against it"), giving
    institutions real causal reach into the Innovation Layer rather
    than a want that just sits there being narrated."""
    feuds: list[dict] = field(default_factory=list)
    """v0.87.11, "generational feuds between FAMILY institutions"
    (docs/IDEAS-2026-07-EMERGENCE.md §1). FAMILY-only in practice (no
    consumer reads this for other kinds): `{"family_id": int,
    "formed_tick": int}` — a rival family this institution is feuding
    with, promoted (both directions, symmetric) by `SimulationEngine.
    _maybe_promote_family_feud` once `Settlement.family_feud_counts`
    crosses `FAMILY_FEUD_PROMOTION_THRESHOLD` real `outcome == "feud"`
    dispute results between the two families' members — a repeated
    PATTERN of conflict, not one bad afternoon. Inherited automatically
    since `member_agent_ids` already outlives individual members (H7's
    anchor point) — a feud doesn't need its own inheritance mechanic,
    membership in the feuding family is enough. Capped at FAMILY_FEUD_
    MAX_STORED (a household plausibly has a handful of real rivals, not
    dozens). Consumed by dispute framing (`rival_families`, same shape
    as the existing `rival_factions`) and `Population._maybe_
    reproduce`'s affinity gate (a stricter bar for a cross-feud-line
    pair — the emergent "Romeo and Juliet" the idea doc names)."""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "founding_tick": self.founding_tick,
            "member_agent_ids": sorted(self.member_agent_ids),
            "name": self.name,
            "beliefs": list(self.beliefs),
            "objective": self.objective,
            "objective_ticks_unmet": self.objective_ticks_unmet,
            "culture_digest": self.culture_digest,
            "feuds": list(self.feuds),
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
            objective=data.get("objective", ""),
            objective_ticks_unmet=data.get("objective_ticks_unmet", 0),
            culture_digest=data.get("culture_digest", ""),
            feuds=list(data.get("feuds", [])),
        )


COUNCIL_OBJECTIVE_DISPOSITION_THRESHOLD = 0.15
"""Same magnitude as `town_brain.COUNCIL_DISPOSITION_TIEBREAK_
THRESHOLD` — how far a council's average ambition/resilience must lean
before `compute_objective` reads it as a real signal, not noise."""

INSTITUTION_OBJECTIVE_PERSISTENCE_THRESHOLD = 3
"""Vision item 2.2: how many consecutive times `compute_objective` must
re-derive the identical want before `Institution.objective_ticks_
unmet` counts as a real, persistent frustration worth grounding a rule
proposal in — one unlucky month reading the same way isn't a standing
grievance yet."""

FAMILY_OBJECTIVE_SMALL_THRESHOLD = 3
"""A FAMILY institution at or below this many living members reads as
"still small" for `compute_objective`'s growth-vs-standing branch."""


def compute_objective(
    institution: "Institution", settlement_summary: dict, council_disposition: dict | None = None,
    village_pillar_lean: float = 0.0,
) -> str:
    """Deterministic (explicit user directive: "Institution objectives:
    these can be deterministic. The LLM should explain the motivation.")
    — one slow-revised line of what this institution WANTS, computed
    from its own real state rather than an LLM impression of it. Same
    signals `town_brain.compute_priority` already reads for the
    settlement as a whole, applied at institution scope."""
    if institution.kind is InstitutionKind.FAMILY:
        if institution.feuds:
            return "see its feud with a rival family finally end"
        if len(institution.member_agent_ids) <= FAMILY_OBJECTIVE_SMALL_THRESHOLD:
            return "see its household grow"
        return "earn a lasting place among the village's council"
    if institution.kind is InstitutionKind.COUNCIL:
        materials_frac = (
            settlement_summary.get("materials", 0.0) / settlement_summary.get("materials_capacity", 1.0)
            if settlement_summary.get("materials_capacity") else 0.0
        )
        if materials_frac < 0.2:
            return "see the village provided for before anything else"
        if council_disposition:
            avg_ambition = council_disposition.get("avg_ambition", 0.0)
            avg_resilience = council_disposition.get("avg_resilience", 0.0)
            if avg_ambition - avg_resilience > COUNCIL_OBJECTIVE_DISPOSITION_THRESHOLD:
                return "see the village grow and its reach widen"
            if avg_resilience - avg_ambition > COUNCIL_OBJECTIVE_DISPOSITION_THRESHOLD:
                return "keep the village secure and at peace"
        # Tier 0's mirror-write -> pillar-authored conversion, third
        # site (docs/ROADMAP-2026-07-REMAINING.md) — the SAME slot
        # `council_disposition`'s own bounded nudge just occupied above
        # (never the materials-need check earlier in this branch),
        # consulted whenever there's no sitting council or its own
        # disposition came back tied. `village_pillar_lean` is the
        # exact precomputed value `SimulationEngine._village_priority_
        # lean()` already builds for `town_brain.compute_priority` —
        # reused here rather than a second parallel signal, since it's
        # the same real question ("does the village's own accumulated
        # sense of itself lean toward growth or safety") asked at a
        # different scope.
        if village_pillar_lean > COUNCIL_OBJECTIVE_DISPOSITION_THRESHOLD:
            return "see the village grow and its reach widen"
        if village_pillar_lean < -COUNCIL_OBJECTIVE_DISPOSITION_THRESHOLD:
            return "keep the village secure and at peace"
        return "keep the village steady"
    if institution.kind is InstitutionKind.GUILD:
        currency_frac = (
            settlement_summary.get("currency", 0.0) / settlement_summary.get("currency_capacity", 1.0)
            if settlement_summary.get("currency_capacity") else 0.0
        )
        if currency_frac < 0.2:
            return "bring in more trade for the village's coffers"
        return "pass its craft on to the next generation"
    # FACTION and any future kind: no mechanically-grounded signal yet
    # (chosen-loyalty clusters carry no settlement-scoped stat this
    # function reads) — a genuine, honest "nothing to compute" rather
    # than a fabricated guess.
    return "hold its own together"


FAMILY_FEUD_PROMOTION_THRESHOLD = 3
"""v0.87.11: how many real `outcome == "feud"` dispute results between
two different FAMILY institutions' members it takes to promote a
`Settlement.family_feud_counts` entry into a durable `Institution.
feuds` entry on both families — same threshold value and "repeated
pattern, not one bad afternoon" rationale as `RITUAL_PROMOTION_
THRESHOLD`."""

FAMILY_FEUD_MAX_STORED = 4
"""Cap on `Institution.feuds` — a household plausibly holds a handful
of real generational rivalries, not dozens; oldest dropped first (same
FIFO-by-append-order discipline as every other capped list here)."""

FAMILY_FEUD_AFFINITY_PENALTY = 0.25
"""Extra affinity `Population._maybe_reproduce` demands, on top of the
ordinary `REPRODUCTION_AFFINITY_THRESHOLD`, before a pair from two
feuding families forms a couple — courtship across the feud line is
harder, not impossible: a pair whose bond clears the higher bar is the
emergent "Romeo and Juliet" the idea doc names, falling out of
existing affinity mechanics colliding with this one gate rather than
any scripted event."""
