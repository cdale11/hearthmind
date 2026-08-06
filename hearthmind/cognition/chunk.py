"""Tier 7 HCA Stage C, C2 (docs/ROADMAP-2026-07-REMAINING.md, Phase 5,
explicit user instruction "Start C2 [after C1]"): chunking — compile a
RESOLVED impasse into a cheap reusable artifact, so the next occurrence
of the SAME impasse is handled without deliberation.

docs/COGNITIVE-ARCHITECTURE-2026-08-02.md §3/Layer 4: "the resolution
is compiled into a cheap reusable artifact — a cached decision keyed
by the impasse signature, a Tier 6 model update, a new `TriggerRule`,
a revised belief. The next occurrence is handled without
deliberation." `ARTIFACT_KINDS` below is that exact four-item closed
vocabulary, unchanged — this module doesn't invent a fifth kind.

`chunk_signature(impasse)` is C1's own `Impasse` reduced to the key a
chunk is compiled/looked-up under — `f"{kind.value}:{subject}"`, so
two impasses of the SAME kind about the SAME subject (C1's own
`detect_*` functions already guarantee `subject` names the recognizably
same thing an impasse is about) always resolve to the same chunk,
never a fresh one. `ChunkStore` is the bounded, browsable registry:
`compile()` is called ONCE, by whichever real deliberation actually
resolved a NOVEL impasse (C3's future job, or a caller standing in for
it today); `lookup()` is the cheap read every SUBSEQUENT occurrence of
the same signature should try FIRST, before ever reaching for a model
or the LLM (C3's own "cached chunk -> learned model -> LLM" ladder,
Stage C's stated dispatch order) — `record_hit()` is the caller's own
acknowledgment that the chunk's cached resolution was actually reused
instead of deliberating again.

Wired into two real production jobs (`_maybe_schedule_musing`, Phase
8's own pilot; `_maybe_schedule_rule_proposal`, Phase 3's own follow-
up) — see `SimulationEngine`'s own docstrings for each. C1's stated
headline test for THIS layer ("the 591st family extinction consumes no
LLM call") describes what `C2`+`C3` do TOGETHER in production — C3's
own "cheap-resolver dispatch" is the real code path that actually
consults `ChunkStore.lookup()` BEFORE ever considering an LLM call.

**Real expiry (Phase 3, roadmap `docs/ROADMAP-2026-07-REMAINING.md`,
explicit user instruction "start phase 3"), closing the exact gap the
musing pilot's own docstring flagged as an accepted, un-engineered-
around limitation: "a chunk is keyed on subject text alone (no
expiry)... a stale cached outcome could suppress a genuinely-overdue
[decision] for a worsening problem indefinitely."** `compile()` gained
an optional `ttl_ticks` — `None` (every pre-Phase-3 caller, including
`_maybe_schedule_musing`'s own, unchanged) means "never expires,"
byte-for-byte the original behavior; a real caller may now instead ask
for a chunk that expires after a bounded, real number of ticks.
`lookup()` gained an optional `tick` — a chunk found past its own real
`expires_at_tick` is treated as a genuine miss (and deleted outright,
not left to linger for a future eviction pass to clean up), forcing
the next occurrence of that signature to pay for one more real
deliberation rather than being suppressed forever. `tick=None` (any
pre-Phase-3 direct caller) skips expiry checking entirely — every
chunk reads as permanently live, the exact prior behavior."""
from __future__ import annotations

from dataclasses import dataclass, field

from hearthmind.cognition.impasse import Impasse
from hearthmind.cognition.memory_kind import MemoryKind

MEMORY_KIND = MemoryKind.PROCEDURAL
"""D2 (docs/COGNITIVE-ARCHITECTURE-2026-08-02.md §2.1): a compiled
chunk is a cached DECISION (how to act on a recurring impasse), never
a fact — see `hearthmind.cognition.memory_kind`'s own docstring for
the real, mechanically-enforced separation this marker participates
in."""

ARTIFACT_KINDS: tuple[str, ...] = (
    "cached_decision", "model_update", "trigger_rule", "revised_belief",
)
"""HCA's own closed four-item vocabulary for what a chunk's compiled
artifact IS (§3/Layer 4's own worked list) — kept closed rather than
freeform so a future Observatory panel (E1/E2) can render a chunk's
kind without guessing at arbitrary strings, same "closed vocabulary,
open content" discipline `world/ontology.py`'s `MECHANICAL_HOOK_TYPES`
already established for a structurally identical problem."""

CHUNK_STORE_MAX = 500
"""Bounded ring-buffer-style cap on `ChunkStore`'s live chunk count —
same "small, bounded, never grows without limit" discipline every
other runtime-only registry in this codebase already holds to. Evicts
the least-recently-reused chunk first (never the newest, and never a
chunk currently being looked up), so a chunk still actively saving
deliberation survives; one that's stopped mattering is reclaimed."""


def chunk_signature(impasse: Impasse) -> str:
    """The exact key a chunk is compiled and looked up under —
    `impasse.kind` + `impasse.subject`, deliberately NOT `impasse.
    detail` (the human-readable "why," which varies run to run even
    for the recognizably same impasse — e.g. the exact streak count in
    a `no_change` impasse's own detail text). Two impasses that would
    read as "the same problem" to a person always collapse to the same
    signature."""
    return f"{impasse.kind.value}:{impasse.subject}"


@dataclass
class Chunk:
    """One compiled artifact. `resolution` is deliberately untyped
    (`object`) — a cached decision might be a plain string, a dict, a
    `TriggerRule`'s own fields, or a revised belief's text; this module
    only stores and returns it, never inspects or judges its shape
    (that's the caller's own domain, per `artifact_kind`)."""

    signature: str
    artifact_kind: str
    resolution: object
    created_tick: int
    hit_count: int = 0
    last_hit_tick: int | None = None
    expires_at_tick: int | None = None
    """Phase 3's real expiry: `None` (every pre-Phase-3 chunk, and
    every chunk compiled with `ttl_ticks=None`) means "never expires,"
    the original permanent-cache behavior. A real value means `lookup()`
    treats this chunk as a genuine miss — and deletes it — once the
    caller's own `tick` reaches or passes it."""

    def __post_init__(self) -> None:
        if self.artifact_kind not in ARTIFACT_KINDS:
            raise ValueError(
                f"artifact_kind {self.artifact_kind!r} is not one of HCA's own closed vocabulary {ARTIFACT_KINDS}"
            )


@dataclass
class ChunkStore:
    """The bounded registry. `compile()`/`lookup()`/`record_hit()` are
    the whole real interface — no other method mutates `_chunks`."""

    _chunks: dict[str, Chunk] = field(default_factory=dict)

    def compile(
        self, impasse: Impasse, artifact_kind: str, resolution: object, tick: int, ttl_ticks: int | None = None,
    ) -> Chunk:
        """Compiles a NEWLY-resolved impasse into a real chunk,
        replacing any prior chunk under the same signature (a
        resolution can legitimately be re-compiled if the world's own
        understanding of the same recurring problem later changes —
        this is not append-only history, it's a live cache). Enforces
        `CHUNK_STORE_MAX` by evicting the single least-recently-reused
        chunk (by `last_hit_tick`, falling back to `created_tick` for a
        chunk that's never been hit) — never the chunk just compiled.

        `ttl_ticks` (Phase 3): `None` (the default, every pre-Phase-3
        caller) compiles a chunk that never expires, byte-for-byte the
        original behavior. A real value sets `expires_at_tick = tick +
        ttl_ticks` — the caller's own real, reasoned bound on how long
        a cached resolution should be trusted before the underlying
        question genuinely gets re-asked."""
        sig = chunk_signature(impasse)
        expires_at_tick = tick + ttl_ticks if ttl_ticks is not None else None
        chunk = Chunk(
            signature=sig, artifact_kind=artifact_kind, resolution=resolution, created_tick=tick,
            expires_at_tick=expires_at_tick,
        )
        self._chunks[sig] = chunk
        if len(self._chunks) > CHUNK_STORE_MAX:
            self._evict_least_recently_reused(protect=sig)
        return chunk

    def lookup(self, impasse: Impasse, tick: int | None = None) -> Chunk | None:
        """The cheap read a real dispatcher (C3) tries FIRST. Never
        mutates state on an ordinary hit or miss — a lookup that never
        gets acted on (the caller decides to deliberate fresh anyway)
        shouldn't count as a real reuse; call `record_hit()` once the
        cached resolution is actually consumed.

        `tick` (Phase 3): `None` (every pre-Phase-3 caller) skips
        expiry checking entirely, matching the original permanent-cache
        behavior exactly. A real `tick` at or past a found chunk's own
        `expires_at_tick` is the one case this DOES mutate state — the
        stale chunk is deleted outright (not left for a future eviction
        pass), and this call reports a genuine miss, so the caller pays
        for one more real deliberation instead of being suppressed by a
        cache that's outlived its own bound."""
        sig = chunk_signature(impasse)
        chunk = self._chunks.get(sig)
        if chunk is None:
            return None
        if tick is not None and chunk.expires_at_tick is not None and tick >= chunk.expires_at_tick:
            del self._chunks[sig]
            return None
        return chunk

    def record_hit(self, chunk: Chunk, tick: int) -> None:
        """The caller's own acknowledgment that a looked-up chunk's
        cached resolution was genuinely reused instead of
        deliberating again — this is the real signal a future E4
        learning-chart panel (deliberative cost falling as a world
        matures) would plot against."""
        chunk.hit_count += 1
        chunk.last_hit_tick = tick

    def size(self) -> int:
        return len(self._chunks)

    def _evict_least_recently_reused(self, protect: str) -> None:
        candidates = [s for s in self._chunks if s != protect]
        if not candidates:
            return
        oldest = min(
            candidates,
            key=lambda s: self._chunks[s].last_hit_tick
            if self._chunks[s].last_hit_tick is not None else self._chunks[s].created_tick,
        )
        del self._chunks[oldest]
