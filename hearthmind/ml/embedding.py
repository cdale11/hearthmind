"""L1.1 -- semantic embedding of the sim's own vocabulary
(docs/ML-ARCHITECTURE-2026-08-01.md).

A small skip-gram word embedding, trained via negative sampling, over
whatever text corpus a caller supplies (memories, beliefs, dialogue,
folklore -- this module is corpus-agnostic by design, same "decouple
from World internals, let the caller supply the data" discipline
`cross_run.py` already established). Answers the one question every
named consumer (memory retrieval, belief/folklore/dialogue dedup,
`Pillar.word_overlap`, topic novelty, plan encoding, belief-subject
matching) is really asking: "do these two pieces of text mean the same
thing in this world?" -- today answered with raw token overlap, which
cannot see that "the wolves took Bram" and "a predator killed my
brother" are the same memory.

Pure-Python inference always (stdlib only, same fallback contract as
every `cpp/src/` module and every other L-layer piece in this package).
Training is pure-Python SGD too -- word2vec-scale vocabularies in this
project (a few hundred to a few thousand distinct words) don't need
numpy's batching to train in reasonable time, unlike `training.py`'s
MLP path. Weights ship as a versioned JSON blob, same "weights are
world state" discipline as every other L-layer model.

Not wired into any real consumer this pass -- same "ship the
substrate, wire it once a real consumer/corpus exists" discipline
L0/L2.1/L3.1/L3.2 all shipped under.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field

from hearthmind.ml.primitives import sigmoid

SCHEMA_VERSION = 1

# Small enough to train fast on this project's realistic vocabulary
# size (a few hundred to a few thousand distinct words); large enough
# to separate genuinely distinct concepts. Not tuned against a live
# corpus yet -- a reasoned starting point, per this project's own
# "size, measure, report back" discipline for untuned constants.
EMBEDDING_DIM_DEFAULT = 32
WINDOW_DEFAULT = 2
NEGATIVE_SAMPLES_DEFAULT = 5
MIN_COUNT_DEFAULT = 1
EPOCHS_DEFAULT = 20
LEARNING_RATE_DEFAULT = 0.05
# Standard word2vec unigram-distribution smoothing exponent -- flattens
# the sampling distribution so common words don't dominate every
# negative-sample draw.
NEGATIVE_SAMPLING_POWER = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace/non-alnum.
    Deliberately simple -- no stemming/stopwording, since the point is
    co-occurrence structure, not linguistic precision."""
    if not text:
        return []
    return _TOKEN_RE.findall(text.lower())


def build_vocab(corpus: list[str], min_count: int = MIN_COUNT_DEFAULT) -> dict[str, int]:
    """word -> stable index. Ordered by descending frequency, ties
    broken alphabetically -- deterministic regardless of input order,
    so training is reproducible given the same corpus + seed."""
    counts: dict[str, int] = {}
    for text in corpus:
        for tok in tokenize(text):
            counts[tok] = counts.get(tok, 0) + 1
    kept = [w for w, c in counts.items() if c >= min_count]
    kept.sort(key=lambda w: (-counts[w], w))
    return {w: i for i, w in enumerate(kept)}


def generate_skipgram_pairs(
    tokenized_sentences: list[list[str]], window: int = WINDOW_DEFAULT
) -> list[tuple[str, str]]:
    """Every (center, context) pair within `window` tokens on either
    side, sentence-bounded (never crosses a sentence boundary -- two
    unrelated sentences shouldn't be treated as co-occurring)."""
    pairs: list[tuple[str, str]] = []
    for sentence in tokenized_sentences:
        n = len(sentence)
        for i, center in enumerate(sentence):
            lo = max(0, i - window)
            hi = min(n, i + window + 1)
            for j in range(lo, hi):
                if j == i:
                    continue
                pairs.append((center, sentence[j]))
    return pairs


def _negative_sampling_table(counts: dict[str, int], vocab: dict[str, int]) -> list[int]:
    """A flat table of vocab indices, each word repeated proportional
    to count**0.75 -- sampling from this table approximates the
    standard word2vec negative-sampling unigram^0.75 distribution
    without needing a real weighted-choice structure for this small a
    vocabulary."""
    table: list[int] = []
    for w, idx in vocab.items():
        weight = max(1, round(counts.get(w, 1) ** NEGATIVE_SAMPLING_POWER * 100))
        table.extend([idx] * weight)
    return table or [0]


def _zero_vector(dim: int) -> list[float]:
    return [0.0] * dim


def _cosine(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return sum(av * bv for av, bv in zip(a, b)) / (na * nb)


@dataclass
class SkipGramEmbedding:
    """`target_vectors`/`context_vectors` are word2vec's standard two
    matrices (a word's meaning-as-subject and meaning-as-context are
    trained separately, then only `target_vectors` is used at
    inference time -- `context_vectors` exists purely to make negative
    sampling trainable)."""

    vocab: dict[str, int]
    dim: int
    target_vectors: list[list[float]]
    context_vectors: list[list[float]] = field(default_factory=list)

    def vector(self, word: str) -> list[float] | None:
        idx = self.vocab.get(word)
        if idx is None:
            return None
        return self.target_vectors[idx]

    def similarity(self, word_a: str, word_b: str) -> float | None:
        va, vb = self.vector(word_a), self.vector(word_b)
        if va is None or vb is None:
            return None
        return _cosine(va, vb)

    def text_vector(self, text: str) -> list[float]:
        """Bag-of-words average over every known token. Unknown-only
        (or empty) text degrades to a genuine zero vector -- an honest
        "no signal" reading, never a fabricated one."""
        vecs = [v for tok in tokenize(text) if (v := self.vector(tok)) is not None]
        if not vecs:
            return _zero_vector(self.dim)
        return [sum(vs) / len(vecs) for vs in zip(*vecs)]

    def text_similarity(self, text_a: str, text_b: str) -> float:
        """"Do these two pieces of text mean the same thing?" -- the
        one question every named L1.1 consumer is really asking.
        `0.0` (never a crash) when either side has no known vocabulary
        at all."""
        return _cosine(self.text_vector(text_a), self.text_vector(text_b))

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "skipgram_embedding",
            "dim": self.dim,
            "vocab": self.vocab,
            "target_vectors": self.target_vectors,
            "context_vectors": self.context_vectors,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SkipGramEmbedding":
        if d.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported weight blob schema_version={d.get('schema_version')!r}")
        return cls(
            vocab=dict(d["vocab"]),
            dim=d["dim"],
            target_vectors=[list(v) for v in d["target_vectors"]],
            context_vectors=[list(v) for v in d.get("context_vectors", [])],
        )


def train_skipgram(
    corpus: list[str],
    dim: int = EMBEDDING_DIM_DEFAULT,
    window: int = WINDOW_DEFAULT,
    negative_samples: int = NEGATIVE_SAMPLES_DEFAULT,
    epochs: int = EPOCHS_DEFAULT,
    learning_rate: float = LEARNING_RATE_DEFAULT,
    min_count: int = MIN_COUNT_DEFAULT,
    seed: int = 0,
) -> SkipGramEmbedding:
    """Pure-Python skip-gram-with-negative-sampling SGD. A caller-
    supplied `corpus` of raw sentences -- this function never reaches
    into `World`/`Agent` state itself, per the module's own corpus-
    agnostic design. An empty/too-small corpus (no pairs at all)
    degrades to a real, zero-vector, structurally valid embedding
    rather than raising."""
    rng = random.Random(seed)
    counts: dict[str, int] = {}
    tokenized: list[list[str]] = []
    for text in corpus:
        toks = tokenize(text)
        tokenized.append(toks)
        for t in toks:
            counts[t] = counts.get(t, 0) + 1
    vocab = build_vocab(corpus, min_count=min_count)
    n = len(vocab)
    scale = (1.0 / max(1, dim)) ** 0.5
    target = [[rng.uniform(-scale, scale) for _ in range(dim)] for _ in range(n)]
    context = [[rng.uniform(-scale, scale) for _ in range(dim)] for _ in range(n)]
    if n == 0:
        return SkipGramEmbedding(vocab=vocab, dim=dim, target_vectors=target, context_vectors=context)

    pairs = generate_skipgram_pairs(tokenized, window=window)
    neg_table = _negative_sampling_table(counts, vocab)

    for _epoch in range(epochs):
        rng.shuffle(pairs)
        for center, ctx in pairs:
            c_idx = vocab.get(center)
            o_idx = vocab.get(ctx)
            if c_idx is None or o_idx is None:
                continue
            v_c = target[c_idx]
            samples = [(o_idx, 1.0)]
            for _ in range(negative_samples):
                neg_idx = neg_table[rng.randrange(len(neg_table))]
                if neg_idx == o_idx:
                    continue
                samples.append((neg_idx, 0.0))

            grad_vc = [0.0] * dim
            for word_idx, label in samples:
                u = context[word_idx]
                z = sum(vc_i * u_i for vc_i, u_i in zip(v_c, u))
                p = sigmoid(z)
                g = (p - label) * learning_rate
                for i in range(dim):
                    grad_vc[i] += g * u[i]
                    u[i] -= g * v_c[i]
            for i in range(dim):
                v_c[i] -= grad_vc[i]

    return SkipGramEmbedding(vocab=vocab, dim=dim, target_vectors=target, context_vectors=context)
