"""Tier 7 HCA Stage D, D2 (docs/ROADMAP-2026-07-REMAINING.md, Phase 6,
explicit user instruction "Start D2"): declarative/procedural
separation made architectural (docs/COGNITIVE-ARCHITECTURE-2026-08-02.
md §2.1, the Standard Model of Mind's own first structural commitment:
"Separate declarative and procedural long-term memory").

Before this module, the distinction was real in this codebase but only
INFORMAL — nothing gave a caller a canonical, queryable answer to "is
this a declarative or a procedural memory structure." `MemoryKind` is
that real type; `MEMORY_KIND` is the module-level marker convention
(exactly `hearthmind.cognition.workspace.Domain`'s own `SPECIALIST_
DOMAIN` shape, Stage H's proven pattern) a real cognition module
declares itself with:

    declarative  -- `hearthmind.cognition.activation` (D1's own ACT-R
                    equation over `Agent.memories`/`memory_salience`/
                    `memory_causes`/`memory_ticks` — facts an agent
                    KNOWS) and `hearthmind.agents.agent`'s memory-
                    bearing fields it scores (`memories`, `semantic_
                    memories`, `core_memories`, `beliefs`, `secrets`,
                    `lessons`, `working_memory`).
    procedural   -- `hearthmind.cognition.chunk` (C2's `ChunkStore` —
                    cached DECISIONS, i.e. HOW to act on a recurring
                    impasse, not facts) and `world.ontology.
                    TriggerRule` (a compiled condition->action rule,
                    the same "how" category). C3's `hearthmind.
                    cognition.dispatch` deliberately declares NEITHER
                    kind — it imports `chunk` (procedural) by design,
                    since it IS the real neutral composition layer the
                    two systems meet through, not a third kind to
                    invent; a module with no marker is simply outside
                    this check's scope, same as WORLD-domain modules
                    were exempt from H1's own check.

Mechanically enforced the same way Stage H enforced cognitive-domain
write scope: `scripts/verify_runtime_invariant.py`'s `check_memory_
kind_separation()` — a module marked `declarative` may never import
from a `procedural`-marked module and vice versa. The real tree is
already clean under this rule (`activation.py` never imported `chunk.
py`, and `chunk.py` never imported `agent.py`, before this module
existed) — same "formalize/enforce what's already true" shape B0.1/H1
both used; this is a real, checkable architectural fact now, not a
coincidence nobody could verify."""
from __future__ import annotations

from enum import Enum


class MemoryKind(Enum):
    DECLARATIVE = "declarative"
    PROCEDURAL = "procedural"


MEMORY_KIND_MARKER_NAME = "MEMORY_KIND"
"""The module-level constant name a real cognition/memory module
declares itself with (`MEMORY_KIND = MemoryKind.DECLARATIVE`) — see
this module's own docstring. Read by `scripts/verify_runtime_
invariant.py`'s `check_memory_kind_separation()`, same shape `Domain`'s
own `SPECIALIST_DOMAIN` marker uses for H1's cognitive-domain check."""


# The real, explicit classification this codebase's own memory-bearing
# structures fall into today — not every conceivable future store, only
# what's actually shipped, so this never claims more precision than the
# real system has. `memory_kind_of()` is the one queryable answer a
# future Observatory panel (Stage E) or consolidation job can call
# instead of re-deriving the distinction from naming convention.
DECLARATIVE_STORE_NAMES = (
    "memories", "memory_salience", "memory_causes", "memory_ticks",
    "semantic_memories", "core_memories", "core_memory_salience",
    "beliefs", "secrets", "lessons", "working_memory",
)
"""Real `Agent` attribute names holding declarative memory (facts an
agent knows/remembers) — every one index-aligned or otherwise paired
with `memories` per their own docstrings in `hearthmind/agents/
agent.py`, consumed by D1's `retrieve_relevant_memories`."""

PROCEDURAL_STORE_NAMES = ("chunk", "trigger_rule", "compiled_reaction")
"""Real procedural-memory artifact kinds — a compiled DECISION about
how to act, not a fact. `chunk` is C2's `ChunkStore` entry (its own
`ARTIFACT_KINDS`: `cached_decision`/`model_update`/`trigger_rule`/
`revised_belief` — all four are HOW-to-act artifacts, even the ones
named after a belief, since what's cached is the resolution, not the
belief content itself); `trigger_rule` is `world.ontology.TriggerRule`
directly; `composite_reaction` is `world.reactions.CompositeReaction`
(A18's own condition->consequence rule, the same shape)."""


def memory_kind_of(store_name: str) -> "MemoryKind | None":
    """The real, single queryable answer this module exists to give —
    `None` for a name this classification doesn't recognize (never
    guessed at)."""
    if store_name in DECLARATIVE_STORE_NAMES:
        return MemoryKind.DECLARATIVE
    if store_name in PROCEDURAL_STORE_NAMES:
        return MemoryKind.PROCEDURAL
    return None
