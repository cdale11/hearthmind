#!/usr/bin/env python3
"""Standalone verification for L1.1 (hearthmind/ml/embedding.py) --
semantic embedding of the sim's own vocabulary. No unittest, per this
project's standing "verification is live diagnostics + ad-hoc scripts"
rule. Run: python3 scripts/verify_ml_l1_embedding.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearthmind.ml.embedding import (  # noqa: E402
    SkipGramEmbedding,
    build_vocab,
    generate_skipgram_pairs,
    tokenize,
    train_skipgram,
)

CHECKS = []


def check(name, condition):
    CHECKS.append((name, bool(condition)))
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {name}")


def main():
    # 1. tokenize: lowercase, strip punctuation, split whitespace.
    check(
        "tokenize lowercases and strips punctuation",
        tokenize("The Wolves Took Bram!") == ["the", "wolves", "took", "bram"],
    )
    check("tokenize empty string -> []", tokenize("") == [])
    check(
        "tokenize handles numbers/hyphens as separators",
        tokenize("tick-1200 happened") == ["tick", "1200", "happened"],
    )

    # 2. build_vocab: min_count filtering, deterministic frequency order.
    corpus = ["a a a b b c", "a b"]
    vocab = build_vocab(corpus, min_count=1)
    check(
        "build_vocab orders by descending frequency (a > b > c)",
        list(vocab.keys()) == ["a", "b", "c"],
    )
    vocab2 = build_vocab(corpus, min_count=2)
    check(
        "build_vocab min_count filters rare words",
        set(vocab2.keys()) == {"a", "b"},
    )
    check(
        "build_vocab is deterministic across repeated calls",
        build_vocab(corpus, min_count=1) == vocab,
    )

    # 3. generate_skipgram_pairs: hand-checked window=1 example, sentence-bounded.
    pairs = generate_skipgram_pairs([["x", "y", "z"]], window=1)
    check(
        "skipgram pairs, window=1, hand-checked",
        sorted(pairs) == sorted([("x", "y"), ("y", "x"), ("y", "z"), ("z", "y")]),
    )
    cross_sentence_pairs = generate_skipgram_pairs([["x"], ["y"]], window=5)
    check(
        "skipgram pairs never cross a sentence boundary",
        cross_sentence_pairs == [],
    )

    # 4. train_skipgram: empty corpus degrades gracefully.
    empty_emb = train_skipgram([], dim=8, epochs=1)
    check(
        "empty corpus yields an empty, structurally valid embedding",
        empty_emb.vocab == {} and empty_emb.target_vectors == [],
    )
    check(
        "text_vector on empty embedding degrades to a zero vector",
        empty_emb.text_vector("anything at all") == [0.0] * 8,
    )
    check(
        "text_similarity of two zero-vector texts is 0.0, never a crash",
        empty_emb.text_similarity("a", "b") == 0.0,
    )

    # 5. Real headline test -- the architecture doc's own worked example:
    #    "the wolves took Bram" and "a predator killed my brother" should
    #    read as thematically closer than either does to an unrelated
    #    harvest sentence, once trained on a corpus with real repeated
    #    co-occurrence structure around each theme (memories/beliefs get
    #    retold with variation, same as this project's real corpus would).
    predator_theme = [
        "the wolves took bram from the field last night",
        "a predator killed my brother near the treeline",
        "the pack of wolves attacked the herd again this week",
        "wolves killed the grazer herd near the pasture",
        "a predator attack left the village afraid of the woods",
        "the wolves returned and took another animal",
        "everyone fears the predator that stalks the herd",
        "the pack attacked again, wolves are a real danger now",
    ]
    harvest_theme = [
        "the harvest was good this year, plenty of wheat",
        "the farmers gathered a strong harvest from the fields",
        "wheat and barley filled the granary after the harvest",
        "the crop this season was the best the village has seen",
        "farmers celebrated a bountiful harvest with a festival",
        "the granary is full thanks to a strong wheat harvest",
        "good weather brought a fine harvest of wheat and barley",
        "the village stored plenty of grain after this harvest",
    ]
    corpus2 = predator_theme + harvest_theme
    emb = train_skipgram(corpus2, dim=16, window=3, negative_samples=4, epochs=200, seed=42)

    sim_within_predator = emb.text_similarity(
        "the wolves took bram from the field last night",
        "a predator killed my brother near the treeline",
    )
    sim_cross_theme = emb.text_similarity(
        "the wolves took bram from the field last night",
        "the harvest was good this year, plenty of wheat",
    )
    check(
        f"headline: same-theme similarity ({sim_within_predator:.3f}) "
        f"exceeds cross-theme similarity ({sim_cross_theme:.3f})",
        sim_within_predator > sim_cross_theme,
    )

    sim_within_harvest = emb.text_similarity(
        "the harvest was good this year, plenty of wheat",
        "farmers celebrated a bountiful harvest with a festival",
    )
    check(
        f"same-theme (harvest) similarity ({sim_within_harvest:.3f}) "
        f"also exceeds cross-theme ({sim_cross_theme:.3f})",
        sim_within_harvest > sim_cross_theme,
    )

    # 6. Determinism: same corpus + same seed -> byte-identical vectors.
    emb_a = train_skipgram(corpus2, dim=8, epochs=5, seed=7)
    emb_b = train_skipgram(corpus2, dim=8, epochs=5, seed=7)
    check(
        "training is deterministic given a fixed seed",
        emb_a.target_vectors == emb_b.target_vectors,
    )
    emb_c = train_skipgram(corpus2, dim=8, epochs=5, seed=8)
    check(
        "a different seed produces a genuinely different embedding",
        emb_a.target_vectors != emb_c.target_vectors,
    )

    # 7. Round-trip + schema rejection.
    d = emb.to_dict()
    restored = SkipGramEmbedding.from_dict(d)
    check(
        "to_dict/from_dict round-trips the vocab and vectors exactly",
        restored.vocab == emb.vocab and restored.target_vectors == emb.target_vectors,
    )
    bad = dict(d)
    bad["schema_version"] = 999
    rejected = False
    try:
        SkipGramEmbedding.from_dict(bad)
    except ValueError:
        rejected = True
    check("from_dict rejects an unsupported schema_version", rejected)

    # 8. Unknown-word queries degrade honestly rather than crashing.
    check("vector() on an unknown word returns None", emb.vector("zzznotaword") is None)
    check(
        "similarity() with an unknown word returns None, not a fabricated score",
        emb.similarity("wolves", "zzznotaword") is None,
    )

    print()
    passed = sum(1 for _, ok in CHECKS if ok)
    total = len(CHECKS)
    print(f"{passed}/{total} checks passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
