#!/usr/bin/env python3
"""Standalone verification for L2.3 (hearthmind/ml/retrieval_scorer.py)
-- the semantic retrieval scorer -- plus its real wiring point in
`agents/agent.py`'s `retrieve_relevant_memories` (an optional
`embedding` param, Tier 6 L1.1's first real production consumer path).
No unittest, per this project's standing "verification is live
diagnostics + ad-hoc scripts" rule.
Run: python3 scripts/verify_ml_l2_3_retrieval_scorer.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearthmind.agents.agent import retrieve_relevant_memories  # noqa: E402
from hearthmind.cognition.activation import base_level_activation  # noqa: E402
from hearthmind.ml.embedding import train_skipgram  # noqa: E402
from hearthmind.ml.retrieval_scorer import (  # noqa: E402
    RetrievalScorer,
    build_retrieval_model,
    build_training_examples,
    encode_candidate,
)
from hearthmind.ml.specialist import LearningSpecialist  # noqa: E402

CHECKS = []


def check(name, condition):
    CHECKS.append((name, bool(condition)))
    print(f"[{'OK' if condition else 'FAIL'}] {name}")


class FakeAgent:
    """Duck-typed stand-in for `agents.agent.Agent` -- `retrieve_
    relevant_memories` only ever reads these four index-aligned lists,
    so a lightweight stand-in is faithful without needing the full
    `AgentStore`-backed class."""

    def __init__(self, memories, salience, causes, ticks):
        self.memories = memories
        self.memory_salience = salience
        self.memory_causes = causes
        self.memory_ticks = ticks


def main():
    # 1. embedding=None reproduces the exact prior bag-of-words path
    #    (parity -- this is the load-bearing "wiring a new optional
    #    param must not change default behavior" check).
    memories = [f"routine day number {i} nothing happened" for i in range(10)]
    memories[3] = "the wolves took bram from the field last night"
    salience = [0.1] * 10
    causes = [""] * 10
    ticks = list(range(0, 100, 10))
    agent = FakeAgent(memories, salience, causes, ticks)

    bow_result = retrieve_relevant_memories(agent, k=3, context="wolves took bram", current_tick=200)
    check(
        "embedding=None (default) still surfaces the real word-overlap match",
        any("wolves took bram" in text for text, _, _ in bow_result),
    )

    # 2. A real trained embedding surfaces a SEMANTICALLY related memory
    #    with ZERO word overlap -- the doc's own worked example, applied
    #    through the real production call path this time, not just
    #    embedding.py's own standalone test.
    predator_corpus = [
        "the wolves took bram from the field last night",
        "a predator killed my brother near the treeline",
        "the pack of wolves attacked the herd again this week",
        "wolves killed the grazer herd near the pasture",
        "a predator attack left the village afraid of the woods",
        "the wolves returned and took another animal",
        "everyone fears the predator that stalks the herd",
        "the pack attacked again, wolves are a real danger now",
        "the harvest was good this year, plenty of wheat",
        "farmers celebrated a bountiful harvest with a festival",
    ]
    emb = train_skipgram(predator_corpus, dim=16, window=3, negative_samples=4, epochs=200, seed=42)

    memories2 = [f"routine day number {i} nothing happened" for i in range(10)]
    memories2[3] = "the wolves took bram from the field last night"
    agent2 = FakeAgent(memories2, salience[:], causes[:], ticks[:])

    # "a predator killed someone" shares NO tokens with memories2[3]
    # ("the wolves took bram...") once stopwords are stripped, so the
    # bag-of-words path should score it 0.0 relevance -- confirmed
    # first as the honest baseline this improves on.
    no_embed_result = retrieve_relevant_memories(
        agent2, k=1, context="a predator killed someone", current_tick=200,
    )
    check(
        "baseline (no embedding): zero word overlap means the semantically-related memory is NOT surfaced",
        "wolves took bram" not in no_embed_result[0][0],
    )

    with_embed_result = retrieve_relevant_memories(
        agent2, k=1, context="a predator killed someone", current_tick=200, embedding=emb,
    )
    check(
        "headline: a real trained embedding surfaces the semantically-related memory with ZERO word overlap",
        "wolves took bram" in with_embed_result[0][0],
    )

    # 3. encode_candidate matches a hand-computed base_level_activation call.
    x = encode_candidate([50], 100, salience=0.5, relevance=0.8, causal_present=True)
    expected_bla = base_level_activation([50], 100)
    check(
        "encode_candidate's first slot matches a direct base_level_activation call",
        abs(x[0] - expected_bla) < 1e-9,
    )
    check("encode_candidate encodes causal_present as 1.0/0.0", x[3] == 1.0)
    x_false = encode_candidate([50], 100, salience=0.5, relevance=0.8, causal_present=False)
    check("encode_candidate encodes a False causal flag as 0.0", x_false[3] == 0.0)

    # 4. Model shape + sigmoid bounds.
    model = build_retrieval_model(hidden_dims=(4,), seed=0)
    check("build_retrieval_model has a single scalar output", model.layers[-1].out_dim == 1)
    out = model.forward([0.0] * model.layers[0].in_dim)
    check("a fresh retrieval model's score is a valid sigmoid probability", 0.0 <= out[0] <= 1.0)

    # 5. RetrievalScorer.rank: real production-shaped call.
    scorer = RetrievalScorer(specialist=LearningSpecialist(build_retrieval_model(seed=1)))
    candidates = [
        ([10], 100, 0.9, 0.9, True, 0),
        ([90], 100, 0.1, 0.1, False, 1),
        ([50], 100, 0.5, 0.5, False, 2),
    ]
    ranked = scorer.rank(candidates, k=2)
    check("RetrievalScorer.rank returns exactly k indices", len(ranked) == 2)
    check("RetrievalScorer.rank returns real candidate indices, not fabricated ones", set(ranked) <= {0, 1, 2})

    # 6. build_training_examples correctness.
    features = [([10], 100, 0.9, 0.9, True), ([90], 100, 0.1, 0.1, False)]
    labels = [1.0, 0.0]
    examples = build_training_examples(features, labels)
    check("build_training_examples produces one example per (candidate, label) pair", len(examples) == 2)
    check("build_training_examples' target is the real supplied label, not fabricated", examples[0].y == [1.0] and examples[1].y == [0.0])

    # 7. Headline: a trained scorer separates "good" from "bad"
    #    candidates by the real four-feature combination, not just
    #    memorizing one input.
    train_features = []
    train_labels = []
    for i in range(60):
        if i % 2 == 0:
            # A "good" candidate: recent, salient, relevant, causally linked.
            train_features.append(([95 + (i % 5)], 100, 0.9, 0.9, True))
            train_labels.append(1.0)
        else:
            # A "bad" candidate: stale, low-salience, irrelevant, no causal link.
            train_features.append(([5 + (i % 5)], 100, 0.05, 0.05, False))
            train_labels.append(0.0)
    trained_examples = build_training_examples(train_features, train_labels)
    trained_scorer = RetrievalScorer(specialist=LearningSpecialist(build_retrieval_model(seed=2)))
    result = trained_scorer.learn(trained_examples, holdout_examples=[], tick=1, epochs=150, learning_rate=0.3)
    check("headline training run reports accepted", result.accepted)

    good_score = trained_scorer.score([98], 100, 0.9, 0.9, True)
    bad_score = trained_scorer.score([6], 100, 0.05, 0.05, False)
    check(
        f"headline: trained scorer separates a good candidate (score={good_score:.3f}) "
        f"from a bad one (score={bad_score:.3f})",
        good_score > bad_score + 0.3,
    )

    print()
    passed = sum(1 for _, ok in CHECKS if ok)
    total = len(CHECKS)
    print(f"{passed}/{total} checks passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
