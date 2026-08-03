#!/usr/bin/env python3
"""Standalone verification for Tier 6's L2.1, the value/consequence
model (hearthmind/ml/value_model.py). Same convention as every sibling
scripts/verify_*.py: no unittest, no CI pipeline, run manually.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.ml.value_model import (
    VALUE_MODEL_SCHEMA,
    ValueConsequenceModel,
    compute_consequence_label,
    make_training_example,
    rank_by_predicted_value,
)

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def check_schema():
    check("schema has a real numeric dimension", VALUE_MODEL_SCHEMA.dim() == len(VALUE_MODEL_SCHEMA.numeric_fields))
    check("schema covers all four named real state fields",
          set(VALUE_MODEL_SCHEMA.numeric_fields) == {
              "emotion_intensity", "recent_event_count_k", "relationship_extremity", "is_core_cast",
          })


def check_label_formula():
    check("magnitude alone with no life event is passed through unchanged (below 1.0)",
          compute_consequence_label(0.4, life_event_followed=False) == 0.4)
    check("a real life event genuinely bumps the label",
          compute_consequence_label(0.4, life_event_followed=True) > 0.4)
    check("the bump is additive+clamped, never exceeding 1.0",
          compute_consequence_label(0.95, life_event_followed=True) == 1.0)
    check("a magnitude=0 observation with a real life event still registers above zero",
          compute_consequence_label(0.0, life_event_followed=True) > 0.0)
    check("magnitude is clamped into [0, 1] even if handed something out of range",
          compute_consequence_label(-0.5, life_event_followed=False) == 0.0
          and compute_consequence_label(1.5, life_event_followed=False) == 1.0)


def check_encoder_and_example_shape():
    ex = make_training_example(
        {"emotion_intensity": 0.5, "recent_event_count_k": 0.2, "relationship_extremity": 0.3, "is_core_cast": 1.0},
        magnitude=0.5, life_event_followed=False,
    )
    check("training example vector matches the schema dimension", len(ex.x) == VALUE_MODEL_SCHEMA.dim())
    check("training example y carries the real computed label", ex.y == [compute_consequence_label(0.5, False)])


def check_missing_field_degrades_gracefully():
    ex = make_training_example({"emotion_intensity": 0.7}, magnitude=0.3, life_event_followed=False)
    check("a partially-filled feature dict never raises, produces a real vector", len(ex.x) == VALUE_MODEL_SCHEMA.dim())


def synthetic_dataset(rng, n):
    """A real, learnable synthetic relationship: consequence scales
    with emotion intensity and relationship extremity, is somewhat
    higher for core-cast agents (more of their state is narratively
    tracked), and a real life-event bump is folded in for a genuine
    fraction of examples -- exercising `compute_consequence_label`
    itself, not a separately-invented target."""
    examples = []
    for _ in range(n):
        emotion_intensity = rng.uniform(0.0, 1.0)
        recent_event_count_k = rng.uniform(0.0, 1.0)
        relationship_extremity = rng.uniform(0.0, 1.0)
        is_core_cast = 1.0 if rng.random() < 0.3 else 0.0
        base_magnitude = min(1.0, 0.15 + emotion_intensity * 0.5 + relationship_extremity * 0.3 + is_core_cast * 0.1)
        life_event_followed = rng.random() < (0.15 + base_magnitude * 0.3)
        features = {
            "emotion_intensity": emotion_intensity, "recent_event_count_k": recent_event_count_k,
            "relationship_extremity": relationship_extremity, "is_core_cast": is_core_cast,
        }
        examples.append((features, base_magnitude, life_event_followed))
    return examples


def check_training_reduces_loss():
    rng = random.Random(7)
    examples = synthetic_dataset(rng, 400)
    train_examples = [make_training_example(f, m, e) for f, m, e in examples[:320]]
    holdout_examples = [make_training_example(f, m, e) for f, m, e in examples[320:]]

    model = ValueConsequenceModel.new(seed=1)
    loss_before = model.evaluate(holdout_examples)
    model.train(train_examples, epochs=100, learning_rate=0.05, seed=2)
    loss_after = model.evaluate(holdout_examples)
    check(
        "training measurably cuts held-out loss on synthetic data",
        loss_after < loss_before * 0.6,
        detail=f"before={loss_before:.4f} after={loss_after:.4f}",
    )


def check_learned_relationship_direction():
    """The trained model should correctly predict a high-emotion,
    high-relationship-extremity core-cast agent as more consequential
    than a calm, socially-neutral, non-core one -- proving it learned
    the real relationship, not just memorized noise."""
    rng = random.Random(11)
    examples = synthetic_dataset(rng, 600)
    train_examples = [make_training_example(f, m, e) for f, m, e in examples]
    model = ValueConsequenceModel.new(seed=3)
    model.train(train_examples, epochs=120, learning_rate=0.05, seed=4)

    high = model.predict({
        "emotion_intensity": 0.95, "recent_event_count_k": 0.5, "relationship_extremity": 0.9, "is_core_cast": 1.0,
    })
    low = model.predict({
        "emotion_intensity": 0.05, "recent_event_count_k": 0.1, "relationship_extremity": 0.05, "is_core_cast": 0.0,
    })
    check(
        "a genuinely high-consequence agent scores higher than a genuinely low one",
        high > low,
        detail=f"high={high:.4f} low={low:.4f}",
    )
    check("predictions stay within the real [0, 1] bound (sigmoid output head)", 0.0 <= high <= 1.0 and 0.0 <= low <= 1.0)


def check_rank_by_predicted_value():
    rng = random.Random(23)
    examples = synthetic_dataset(rng, 500)
    train_examples = [make_training_example(f, m, e) for f, m, e in examples]
    model = ValueConsequenceModel.new(seed=5)
    model.train(train_examples, epochs=100, learning_rate=0.05, seed=6)

    candidates = [
        {"emotion_intensity": 0.9, "recent_event_count_k": 0.4, "relationship_extremity": 0.8, "is_core_cast": 1.0},
        {"emotion_intensity": 0.05, "recent_event_count_k": 0.05, "relationship_extremity": 0.05, "is_core_cast": 0.0},
        {"emotion_intensity": 0.5, "recent_event_count_k": 0.3, "relationship_extremity": 0.4, "is_core_cast": 0.0},
    ]
    ranked = rank_by_predicted_value(model, candidates)
    check("ranking is descending by predicted value", ranked[0] is candidates[0] and ranked[-1] is candidates[1])
    check("rank_by_predicted_value never mutates or drops a candidate", sorted(id(c) for c in ranked) == sorted(id(c) for c in candidates))

    tied = [{"emotion_intensity": 0.5, "recent_event_count_k": 0.5, "relationship_extremity": 0.5, "is_core_cast": 0.0} for _ in range(3)]
    ranked_tied = rank_by_predicted_value(model, tied)
    check("ties break on stable input order, never randomly", ranked_tied[0] is tied[0] and ranked_tied[1] is tied[1] and ranked_tied[2] is tied[2])


def main():
    check_schema()
    check_label_formula()
    check_encoder_and_example_shape()
    check_missing_field_degrades_gracefully()
    check_training_reduces_loss()
    check_learned_relationship_direction()
    check_rank_by_predicted_value()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
