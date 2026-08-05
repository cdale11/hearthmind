"""Tier 7 HCA Stage D, D1 (docs/ROADMAP-2026-07-REMAINING.md, Phase 6,
explicit user instruction "Start phase 6 is phase 5 is done with D1"):
ACT-R base-level memory activation, replacing the four hand-tuned
`MEMORY_RETRIEVAL_*` weights `retrieve_relevant_memories` previously
combined by flat weighted sum (docs/COGNITIVE-ARCHITECTURE-2026-08-02.
md §2.5):

    A_i = ln( Σ_j (t − t_j)^(−d) )  +  Σ_k W_k · S_ki  +  ε
          └── recency + frequency ──┘   └─ spreading ─┘   noise

The first term unifies recency AND frequency into one real quantity —
a memory rehearsed/presented several times decays slower than one seen
once, and a recently-formed memory scores higher than an old one at
the same rehearsal count, both from the SAME sum rather than two
separately hand-weighted heuristics. `d ≈ 0.5` per the ACT-R
literature this doc cites. Honest scope trim, stated up front: `Agent`
carries no per-memory rehearsal/access counter today (unlike `Pillar.
memory_access`, B8's own reinforce counters — a real signal, but scoped
to `Pillar`, never threaded onto `Agent`) — every memory here has
exactly ONE real presentation, its formation tick (`Agent.memory_
ticks`). Multi-presentation counting is real, distinct future work if
an `Agent`-side rehearsal counter is ever added; `base_level_
activation` already accepts a real list of presentation ticks, not
just one, so that extension needs no signature change here.

The second term (spreading/associative activation) is where this
project's own two remaining real signals — keyword-overlap relevance
to the current context, and a small causal-tag bonus — enter, each as
a real weighted "source" `S_k` rather than a second independent
additive heuristic; salience (already a real, separately-computed
per-memory importance score, `Agent.memory_salience`) is the third.
`ε` (noise) is deliberately omitted — this codebase's own standing
"no randomness in arbitration" discipline (`hearthmind.cognition.
workspace`'s B2 arbitration redesign) applies equally here: memory
retrieval must stay replayable and its ranking must always be
answerable, which a stochastic term would break."""
from __future__ import annotations

import math

ACTIVATION_DECAY_EXPONENT = 0.5
"""`d` in the ACT-R base-level equation — the literature's own
canonical value (docs/COGNITIVE-ARCHITECTURE-2026-08-02.md §2.5,
"d ≈ 0.5"), not re-tuned against this project's own data (no training
signal exists to tune it against yet)."""

ACTIVATION_FLOOR = -10.0
"""`base_level_activation`'s return for a memory with NO real
presentations (an empty `presentation_ticks`, e.g. a genuinely
malformed/zero-length entry) — a large, deliberately negative
placeholder so such an entry always ranks last rather than raising or
silently scoring like a fresh one."""

ACTIVATION_MIN_AGE_TICKS = 1
"""`(t − t_j)` is floored at this before exponentiation — a same-tick
presentation (`t == t_j`, the tick a memory was JUST formed) would
otherwise raise `age ** (-d)` to a `0 ** negative` ZeroDivisionError;
flooring at 1 tick treats "just now" as the most-recent-possible real
age rather than a special case."""

ACTIVATION_SALIENCE_GAIN = 0.6
ACTIVATION_RELEVANCE_GAIN = 1.0
ACTIVATION_CAUSAL_GAIN = 0.3
"""The three real spreading-activation source gains (`W_k` in the
equation above) — relevance to the current context stays the single
strongest source (matching the deleted `MEMORY_RETRIEVAL_RELEVANCE_
WEIGHT`'s own relative weight, the highest of the four), salience a
real but smaller source (mirroring the deleted `_SALIENCE_WEIGHT`'s
own smaller relative weight), and the causal-tag bonus stays the
smallest (mirroring `_CAUSAL_BONUS`) — same relative ordering as the
formula this replaces, carried over deliberately rather than
re-derived from nothing, since no live-diagnostic archive exists in
this offline environment to re-tune against."""


def base_level_activation(
    presentation_ticks: "list[int]", current_tick: int, decay: float = ACTIVATION_DECAY_EXPONENT,
) -> float:
    """The real ACT-R recency+frequency term: `ln(Σ_j (t−t_j)^(−d))`.
    `presentation_ticks` is every real tick this memory was presented/
    formed at (today always a single-element list — this agent's own
    `Agent.memory_ticks[i]` — see this module's own docstring on why);
    `current_tick` is `t`, the real "now" the caller is retrieving at.
    A later presentation (smaller age) contributes more; several
    presentations sum, so a repeatedly-reinforced memory activates
    higher than a once-seen one at the same age — the real unification
    of "recency" and "frequency" into one quantity, replacing what were
    two entirely separate (and, for frequency, ABSENT) signals in the
    formula this supersedes."""
    if not presentation_ticks:
        return ACTIVATION_FLOOR
    total = 0.0
    for presented_at in presentation_ticks:
        age = max(current_tick - presented_at, ACTIVATION_MIN_AGE_TICKS)
        total += age ** (-decay)
    return math.log(total)


def spreading_activation(salience: float, relevance: float, causal_present: bool) -> float:
    """The real `Σ_k W_k · S_ki` term — salience/relevance/causal-tag
    as three weighted associative sources, see the module docstring for
    why these three and not a fourth invented one."""
    return (
        ACTIVATION_SALIENCE_GAIN * salience
        + ACTIVATION_RELEVANCE_GAIN * relevance
        + (ACTIVATION_CAUSAL_GAIN if causal_present else 0.0)
    )


def memory_activation(
    presentation_ticks: "list[int]", current_tick: int,
    salience: float, relevance: float, causal_present: bool,
    decay: float = ACTIVATION_DECAY_EXPONENT,
) -> float:
    """The full real base-level + spreading activation score — the one
    number `retrieve_relevant_memories` now sorts by, replacing its
    prior four-constant weighted sum."""
    return (
        base_level_activation(presentation_ticks, current_tick, decay)
        + spreading_activation(salience, relevance, causal_present)
    )
