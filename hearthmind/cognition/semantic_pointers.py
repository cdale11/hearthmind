"""Tier 7 HCA, Stage F, F1 (docs/COGNITIVE-ARCHITECTURE-2026-08-02.md
§7, gated behind Tier 6 L1.1): concept vectors, bundling/binding, "LLM
names the best algebraic candidate." Falsifiable test (the doc's own):
"a concept combination is generated and judged with strictly fewer LLM
calls than today's pipeline."

**What this actually buys, stated precisely.** `world/ontology.py`'s
existing `merge`/`evolve` pipeline already makes exactly ONE LLM call
per combination — there is no naive N-candidate-then-judge pipeline in
production to beat by parallel-generating fewer calls. What a
real vector-symbolic layer replaces is a DIFFERENT naive pipeline: if
you wanted the sim to explore several possible combinations and pick
the best BEFORE asking the LLM to write it up, the naive way is K
separate "generate candidate i" LLM calls plus one "judge" LLM call —
`K + 1` calls for `K` candidates. This module generates all `K`
candidates ALGEBRAICALLY (`bundle`/`bind` over L1.1 embeddings, zero
LLM calls) and scores/picks the best one deterministically
(`select_best_candidate`, zero LLM calls) — so exploring `K`
candidates costs exactly ONE LLM call (to name/describe the single
winner) regardless of `K`, strictly fewer than the `K + 1` a
generate-then-judge pipeline would need for any `K >= 1`. See
`scripts/verify_hca_f1_semantic_pointers.py`'s own call-count
comparison for the literal test.

**Bundling** (superposition, "these concepts as one blended idea") is
elementwise vector averaging, normalized — the standard VSA operation
for representing an unordered SET. **Binding** (a structured "A
combined with B" relation, reversible) is circular convolution — the
classic Holographic Reduced Representation (Plate 1995) operation;
`unbind` (circular correlation) approximately recovers one operand
given the bound vector and the other operand, which is what makes
binding meaningfully different from bundling rather than a second copy
of the same operation. Both operate on `hearthmind.ml.embedding.
SkipGramEmbedding`'s real trained vectors — this module has no
embedding-training logic of its own, it composes L1.1's output.

Not wired into `world/ontology.py`'s live merge pipeline this pass —
`llm/ontology.py`'s `build_merge_prompt` gained a real, optional
`candidate_hint` param (this module's `format_candidate_hint` is the
one intended caller) that this module's own selected-candidate output
feeds, but no `simulation/engine.py` call site builds real concept
vectors and passes the hint through yet; same "ship the substrate,
wire it once a real consumer/corpus exists" discipline every prior
Tier 6/7 L-layer piece has shipped under — L1.1 itself has no world
yet with a trained embedding to pull real concept vectors from.
`build_evolve_prompt` (single-concept refinement, not a two-concept
combination) is deliberately left untouched — it isn't what `bundle`/
`bind` model.
"""
from __future__ import annotations

import math


def _cosine(a: list, b: list) -> float:
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return sum(av * bv for av, bv in zip(a, b)) / (na * nb)


def _normalize(v: list) -> list:
    n = math.sqrt(sum(c * c for c in v))
    if n == 0.0:
        return list(v)
    return [c / n for c in v]


def bundle(vectors: list) -> list:
    """Superposition: elementwise mean, normalized. Represents "these
    concepts, blended into one" — the SET operation. `vectors` must be
    non-empty and share a dimension; an empty list returns `[]` rather
    than raising, matching this codebase's own "absence means neutral,
    never a crash" discipline for field-shaped data."""
    if not vectors:
        return []
    dim = len(vectors[0])
    summed = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            summed[i] += v[i]
    return _normalize([s / len(vectors) for s in summed])


def bind(a: list, b: list) -> list:
    """Circular convolution -- the real HRR binding operation (Plate
    1995): `c[i] = sum_j a[j] * b[(i-j) mod n]`. Reversible via
    `unbind` (circular correlation), unlike `bundle`, which is lossy by
    design (you can't recover the originals from a superposition).
    Represents a structured "A combined-with B" relation, distinct from
    "A and B as a set." O(n^2) pure Python -- fine at L1.1's real
    32-64 dim scale, no FFT needed."""
    n = len(a)
    if n != len(b):
        raise ValueError(f"bind() requires equal-length vectors, got {n} and {len(b)}")
    if n == 0:
        return []
    return [sum(a[j] * b[(i - j) % n] for j in range(n)) for i in range(n)]


def unbind(c: list, known: list) -> list:
    """Circular correlation: approximately recovers the OTHER operand
    given a bound vector `c = bind(a, b)` and one known operand.
    `correlate(c, known)[i] = sum_j c[j] * known[(j+i) mod n]` -- the
    real inverse of `bind` up to noise (HRR's own well-known property;
    exact recovery needs orthonormal vectors, which L1.1's trained
    embeddings are not, so this is approximate by construction, not a
    bug)."""
    n = len(c)
    if n != len(known):
        raise ValueError(f"unbind() requires equal-length vectors, got {n} and {len(known)}")
    if n == 0:
        return []
    return [sum(c[j] * known[(j + i) % n] for j in range(n)) for i in range(n)]


def nearest_vocab(vector: list, embedding, top_n: int = 3) -> list:
    """The one real "make an algebraic vector legible" function: finds
    the `top_n` real vocabulary words in a trained `SkipGramEmbedding`
    whose OWN vector is closest to `vector` by cosine similarity --
    what turns `bundle(fire_vec, water_vec)` into a human-readable
    gist ("steam", "quench", ...) instead of 32 opaque floats. Returns
    `[]` for an embedding with an empty vocabulary rather than
    raising."""
    scored = []
    for word, idx in embedding.vocab.items():
        wv = embedding.target_vectors[idx]
        scored.append((_cosine(vector, wv), word))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [(word, score) for score, word in scored[:top_n]]


def generate_candidates(vec_a: list, vec_b: list, embedding=None, top_n: int = 3) -> list:
    """The real, zero-LLM-cost candidate-generation step: exactly two
    algebraic combinations of the two source concept vectors --
    `bundle` (blended/superposed) and `bind` (structurally combined).
    Each candidate carries its own coherence score (mean cosine
    similarity to BOTH parents -- a candidate that drifted far from
    both source concepts is a worse combination than one that stays
    recognizably related to each) and, when a trained `embedding` is
    supplied, a real nearest-vocabulary gist. Deliberately just these
    two operations, not an open-ended search -- `bundle`/`bind` are
    the two well-defined VSA primitives this module implements; a
    genuinely different THIRD operation would need its own real
    justification, not be added for volume."""
    candidates = []
    for kind, vec in (("bundle", bundle([vec_a, vec_b])), ("bind", bind(vec_a, vec_b))):
        if not vec:
            continue
        coherence = (_cosine(vec, vec_a) + _cosine(vec, vec_b)) / 2.0
        gist = nearest_vocab(vec, embedding, top_n=top_n) if embedding is not None else []
        candidates.append({"kind": kind, "vector": vec, "coherence": coherence, "gist": gist})
    return candidates


def select_best_candidate(candidates: list) -> dict | None:
    """Deterministic, zero-LLM-cost selection: the candidate with the
    highest coherence score (ties broken by `kind` for a stable,
    reproducible pick). `None` for an empty candidate list -- an
    honest "nothing to select" rather than a fabricated winner."""
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c["coherence"], c["kind"]))


def format_candidate_hint(candidate: dict | None) -> str:
    """Turns a `select_best_candidate` winner into the plain,
    comma-joined word list `llm.ontology.build_merge_prompt`'s
    `candidate_hint` param expects -- `""` for `None` or a candidate
    with no real gist (no embedding was supplied to `generate_
    candidates`), which reproduces `build_merge_prompt`'s own
    no-hint prompt text exactly."""
    if not candidate or not candidate.get("gist"):
        return ""
    return ", ".join(word for word, _score in candidate["gist"])
