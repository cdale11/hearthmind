"""B1 "The Pillar abstraction" (docs/MASTERCHECKLIST-2026-07-22.md,
Part B, Stage II step 4 — "the keystone"): the shape a persistent
conscious entity needs — identity, self-model, world-model (typed
theories distinguishing observation from hypothesis), living memory,
objectives, inbox/outbox — proven against ONE pillar (Nature) before
being replicated across the other four, per the roadmap's own
sequencing ("proving the shape before replicating it four more
times").

This is deliberately NOT the "refactor the ~55 scattered jobs into
acts of five pillars" the checklist's B1 spec ultimately asks for —
that's the rest of Stage II (B2's continuous cognitive cycle, B3's
attention scheduler, B4's inter-pillar bus, B7/B9 generalizing this
shape to Humans/Village/Innovation/Reflection). This pass gives
Nature's existing belief-forming job (`llm/nature_mind.py`,
unchanged) a real persistent structure to write into ALONGSIDE the
untouched `World.nature_beliefs` list every existing consumer already
reads — proof the shape holds against a genuine production call site,
not a standalone demo.

`inbox`/`outbox` are structurally present (B4's typed message
vocabulary, `MESSAGE_KINDS`) but stay empty for Nature — a message
needs a second pillar to send to/receive from, which doesn't exist
until a future step."""
from __future__ import annotations

WORLD_MODEL_STATUSES = ("observation", "hypothesis")
"""Distinguishes a directly-observed fact from a theory the pillar has
formed but not confirmed — B9's "distinguishing observation from
hypothesis" line. Every entry written by an LLM belief-forming job
today is a `hypothesis` (a belief can always turn out wrong); a future
producer that mirrors real Body state verbatim could write
`observation` instead."""

MESSAGE_KINDS = (
    "observation", "question", "theory", "hypothesis", "warning",
    "request", "discovery", "disagreement",
)
"""B4's typed inter-pillar message vocabulary, defined here as the
shared contract every pillar's inbox/outbox will use once a second
pillar exists to send/receive with (a later step)."""


def make_world_model_entry(
    entry_id: int, tick: int, subject: str, belief: str, confidence: float,
    status: str = "hypothesis", source: str = "",
) -> dict:
    """One theory a pillar holds about itself or its domain — same
    subject/belief/confidence/revisable shape `Settlement.beliefs`/
    `World.nature_beliefs` already use, plus the explicit
    observation-vs-hypothesis status B9 asks for."""
    if status not in WORLD_MODEL_STATUSES:
        raise ValueError(f"unknown world-model status {status!r}, expected one of {WORLD_MODEL_STATUSES}")
    return {
        "id": entry_id, "tick": tick, "subject": subject, "belief": belief,
        "confidence": max(0.0, min(1.0, confidence)), "status": status, "source": source,
    }


def make_message(
    message_id: int, tick: int, from_pillar: str, to_pillar: str, kind: str,
    summary: str, data: dict | None = None,
) -> dict:
    """One B4 inter-pillar message. Validates `kind` against the closed
    vocabulary above — same "fail loudly at the producer" discipline as
    `world.emergence.make_observation`."""
    if kind not in MESSAGE_KINDS:
        raise ValueError(f"unknown message kind {kind!r}, expected one of {MESSAGE_KINDS}")
    return {
        "id": message_id, "tick": tick, "from_pillar": from_pillar, "to_pillar": to_pillar,
        "kind": kind, "summary": summary, "data": data or {},
    }


class Pillar:
    """One persistent conscious entity's full state. Plain-dict-backed
    (`to_dict`/`from_dict`), same persistence convention as every other
    World-scoped store — no ORM, no separate schema per pillar type."""

    MEMORY_MAX = 40
    """Bounded consolidated-memory cap — a plain FIFO list this pass
    (B8's real consolidate/forget/reinforce cycle is a later step);
    still needs a cap from day one per the standing memory-leak-audit
    discipline (CLAUDE.md's "Memory-leak pattern to audit first")."""

    def __init__(
        self, name: str, description: str = "", self_model: dict | None = None,
        world_model: list[dict] | None = None, memory: list[str] | None = None,
        objectives: list[str] | None = None, inbox: list[dict] | None = None,
        outbox: list[dict] | None = None, next_world_model_id: int = 1, next_message_id: int = 1,
    ) -> None:
        self.name = name
        self.description = description
        self.self_model = self_model if self_model is not None else {}
        self.world_model = world_model if world_model is not None else []
        self.memory = memory if memory is not None else []
        self.objectives = objectives if objectives is not None else []
        self.inbox = inbox if inbox is not None else []
        self.outbox = outbox if outbox is not None else []
        self.next_world_model_id = next_world_model_id
        self.next_message_id = next_message_id

    def upsert_world_model(
        self, tick: int, subject: str, belief: str, confidence: float,
        status: str = "hypothesis", source: str = "", revises_id: int | None = None,
    ) -> dict:
        """Revise an existing entry by id, or append a new one — mirrors
        the revise-by-index-or-append shape every belief-forming job in
        the codebase already uses, against this pillar's own typed
        `world_model` list instead of a bare dict list."""
        if revises_id is not None:
            existing = next((e for e in self.world_model if e["id"] == revises_id), None)
            if existing is not None:
                existing["belief"] = belief
                existing["confidence"] = max(0.0, min(1.0, confidence))
                existing["subject"] = subject
                existing["status"] = status
                existing["tick"] = tick
                return existing
        entry = make_world_model_entry(self.next_world_model_id, tick, subject, belief, confidence, status, source)
        self.next_world_model_id += 1
        self.world_model.append(entry)
        return entry

    def remember(self, note: str) -> None:
        """Appends one consolidated-memory note, capped at `MEMORY_MAX`
        (oldest evicted) — the "keeps years cognitively manageable"
        line from B8, in its simplest possible form."""
        self.memory.append(note)
        if len(self.memory) > self.MEMORY_MAX:
            self.memory = self.memory[-self.MEMORY_MAX:]

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description, "self_model": dict(self.self_model),
            "world_model": [dict(e) for e in self.world_model], "memory": list(self.memory),
            "objectives": list(self.objectives), "inbox": [dict(m) for m in self.inbox],
            "outbox": [dict(m) for m in self.outbox],
            "next_world_model_id": self.next_world_model_id, "next_message_id": self.next_message_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Pillar":
        return cls(
            name=data.get("name", ""), description=data.get("description", ""),
            self_model=dict(data.get("self_model", {})),
            world_model=[dict(e) for e in data.get("world_model", [])],
            memory=list(data.get("memory", [])),
            objectives=list(data.get("objectives", [])),
            inbox=[dict(m) for m in data.get("inbox", [])],
            outbox=[dict(m) for m in data.get("outbox", [])],
            next_world_model_id=data.get("next_world_model_id", 1),
            next_message_id=data.get("next_message_id", 1),
        )


def default_nature_pillar() -> Pillar:
    """Nature's seeded identity/self-model/objectives — genesis-time
    defaults, not LLM-authored (a pillar's sense of what it fundamentally
    is isn't itself a revisable belief the way its `world_model` entries
    are)."""
    return Pillar(
        name="nature",
        description=(
            "The wordless, watching intelligence of the land itself — not a person, "
            "not the village, but the accumulated sense the wilderness has of its own state."
        ),
        self_model={
            "domain": "weather, wildlife, disasters, terrain, the land's own condition",
            "voice": "never speaks as a person; forms impressions, not statements",
        },
        objectives=[
            "notice what threatens or nourishes the land",
            "hold a real, sometimes-wrong sense of its own condition",
        ],
    )
