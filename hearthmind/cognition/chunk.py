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

Deliberately NOT wired into any real production LLM job this pass —
same "ship the interface, wire the first real consumer next"
discipline C1 itself just used, and the same discipline every prior
Stage A/B/G/H item in this codebase has used. C1's stated headline
test for THIS layer ("the 591st family extinction consumes no LLM
call") describes what `C2`+`C3` do TOGETHER in production — C3's own
"cheap-resolver dispatch" is the real code path that would actually
consult `ChunkStore.lookup()` BEFORE ever considering an LLM call;
this module only ships the store `C3` will consult."""
from __future__ import annotations

from dataclasses import dataclass, field

from hearthmind.cognition.impasse import Impasse

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

    def compile(self, impasse: Impasse, artifact_kind: str, resolution: object, tick: int) -> Chunk:
        """Compiles a NEWLY-resolved impasse into a real chunk,
        replacing any prior chunk under the same signature (a
        resolution can legitimately be re-compiled if the world's own
        understanding of the same recurring problem later changes —
        this is not append-only history, it's a live cache). Enforces
        `CHUNK_STORE_MAX` by evicting the single least-recently-reused
        chunk (by `last_hit_tick`, falling back to `created_tick` for a
        chunk that's never been hit) — never the chunk just compiled."""
        sig = chunk_signature(impasse)
        chunk = Chunk(signature=sig, artifact_kind=artifact_kind, resolution=resolution, created_tick=tick)
        self._chunks[sig] = chunk
        if len(self._chunks) > CHUNK_STORE_MAX:
            self._evict_least_recently_reused(protect=sig)
        return chunk

    def lookup(self, impasse: Impasse) -> Chunk | None:
        """The cheap read a real dispatcher (C3) tries FIRST. Never
        mutates state — a lookup that never gets acted on (the caller
        decides to deliberate fresh anyway) shouldn't count as a real
        reuse; call `record_hit()` once the cached resolution is
        actually consumed."""
        return self._chunks.get(chunk_signature(impasse))

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
