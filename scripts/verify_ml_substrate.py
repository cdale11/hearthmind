#!/usr/bin/env python3
"""Standalone verification for hearthmind/ml/ (Tier 6, L0 substrate --
docs/ML-ARCHITECTURE-2026-08-01.md). Same convention as every other
scripts/verify_*.py: no unittest, no CI pipeline, run manually.

Checks the feature encoder, the model primitives (linear/MLP/
calibrator) including weight-blob JSON round-trip, the pure-Python
SGD trainer actually reduces loss on a toy dataset, and -- the load-
bearing check for this pass's "external libraries now permitted"
change (v1.34.171) -- that the numpy-accelerated batch forward pass
is equivalent to the pure-Python forward pass it must match, when
numpy is installed. If numpy isn't installed, that check is skipped
with a note rather than failing: the `ml` extra is optional and the
rest of the substrate must work without it.
"""
import math
import random
import sys
import tempfile
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.ml.encoder import FeatureEncoder, FeatureSchema
from hearthmind.ml.primitives import LinearLayer, MLP, PlattCalibrator, sigmoid
from hearthmind.ml import training as ml_training
from hearthmind.ml.lifelong import CheckpointHistory, ReplayBuffer, passes_shadow_gate

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def check_encoder_basic():
    schema = FeatureSchema(
        numeric_fields=["hunger", "energy"],
        categorical_fields={"season": ["spring", "summer", "autumn", "winter"]},
    )
    enc = FeatureEncoder(schema)
    v = enc.encode({"hunger": 0.5, "energy": 0.8, "season": "autumn"})
    check("encoder: dim matches schema", len(v) == schema.dim(), f"len={len(v)} dim={schema.dim()}")
    check("encoder: numeric values in order", v[0] == 0.5 and v[1] == 0.8, str(v))
    check("encoder: correct one-hot slot set", v[2:] == [0.0, 0.0, 1.0, 0.0], str(v[2:]))


def check_encoder_missing_and_bad_values():
    schema = FeatureSchema(numeric_fields=["a", "b"], categorical_fields={"kind": ["x", "y"]})
    enc = FeatureEncoder(schema)
    v = enc.encode({"a": "not-a-number", "kind": "unrecognized"})
    check("encoder: missing numeric defaults to 0.0", v[1] == 0.0, str(v))
    check("encoder: bad numeric value degrades to 0.0 (never raises)", v[0] == 0.0, str(v))
    check("encoder: unrecognized categorical sets no slot", v[2:] == [0.0, 0.0], str(v[2:]))


def check_linear_layer_forward():
    layer = LinearLayer(weights=[[1.0, 2.0], [0.0, 1.0]], bias=[0.5, -1.0])
    out = layer.forward([1.0, 1.0])
    check("linear layer: hand-computed forward pass", out == [3.5, 0.0], str(out))


def check_mlp_forward_shapes_and_activations():
    model = MLP(
        layers=[
            LinearLayer(weights=[[1.0, -1.0], [1.0, 1.0]], bias=[0.0, 0.0]),
            LinearLayer(weights=[[1.0, 1.0]], bias=[0.0]),
        ],
        output_activation="sigmoid",
    )
    out = model.forward([2.0, 1.0])
    # hidden: relu([2-1, 2+1]) = relu([1,3]) = [1,3]; out pre-sigmoid = 1+3=4
    expected = sigmoid(4.0)
    check("mlp: forward matches hand-computed value", math.isclose(out[0], expected, rel_tol=1e-9), f"{out[0]} vs {expected}")

    softmax_model = MLP(layers=[LinearLayer(weights=[[1.0], [0.0]], bias=[0.0, 0.0])], output_activation="softmax")
    probs = softmax_model.forward([0.0])
    check("mlp: softmax output sums to 1", math.isclose(sum(probs), 1.0, rel_tol=1e-9), str(probs))


def check_weight_blob_round_trip():
    model = MLP.random_init([4, 5, 2], output_activation="sigmoid", seed=42)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "weights.json")
        model.save(path)
        loaded = MLP.load(path)
        x = [0.1, -0.2, 0.3, 0.4]
        out_a = model.forward(x)
        out_b = loaded.forward(x)
        check("mlp: save/load round-trip reproduces forward output exactly", out_a == out_b, f"{out_a} vs {out_b}")

    bad = {"schema_version": 999, "kind": "mlp", "layers": [], "output_activation": "linear"}
    import json
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "bad.json")
        with open(path, "w") as f:
            json.dump(bad, f)
        raised = False
        try:
            MLP.load(path)
        except ValueError:
            raised = True
        check("mlp: load rejects an unsupported schema_version", raised)


def check_calibrator():
    cal = PlattCalibrator(a=2.0, b=-1.0)
    check("calibrator: to_dict/from_dict round-trip", PlattCalibrator.from_dict(cal.to_dict()) == cal)
    scores = [-3.0, -1.0, 0.5, 2.0, 4.0] * 20
    labels = [0.0, 0.0, 1.0, 1.0, 1.0] * 20
    fresh = PlattCalibrator(a=0.1, b=0.0).fit(scores, labels, epochs=300, lr=0.3)
    low = fresh.calibrate(-3.0)
    high = fresh.calibrate(4.0)
    check("calibrator: fit separates low/high scores", low < 0.5 < high, f"low={low:.3f} high={high:.3f}")


def check_sgd_trainer_reduces_loss():
    # Toy regression: y = 2*x0 - x1 + 0.5, plus a bit of noise.
    rng = random.Random(7)
    examples = []
    for _ in range(200):
        x0 = rng.uniform(-1, 1)
        x1 = rng.uniform(-1, 1)
        y = 2.0 * x0 - x1 + 0.5 + rng.uniform(-0.02, 0.02)
        examples.append(ml_training.TrainingExample(x=[x0, x1], y=[y]))

    model = MLP.random_init([2, 4, 1], output_activation="linear", seed=1)
    loss_before = ml_training.mean_loss(model, examples)
    ml_training.train_mlp_sgd(model, examples, epochs=80, learning_rate=0.05, seed=1)
    loss_after = ml_training.mean_loss(model, examples)
    check(
        "sgd trainer: loss drops substantially on a learnable toy task",
        loss_after < loss_before * 0.1,
        f"before={loss_before:.4f} after={loss_after:.4f}",
    )


def check_numpy_equivalence():
    if not ml_training.HAS_NUMPY:
        print("[SKIP] numpy-accelerated forward equivalence -- numpy not installed (ml extra optional)")
        return
    rng = random.Random(3)
    model = MLP.random_init([6, 8, 3], output_activation="sigmoid", seed=9)
    xs = [[rng.uniform(-2, 2) for _ in range(6)] for _ in range(25)]
    py_out = [model.forward(x) for x in xs]
    np_out = ml_training.numpy_batch_forward(model, xs)
    max_diff = max(
        abs(a - b) for row_a, row_b in zip(py_out, np_out) for a, b in zip(row_a, row_b)
    )
    check(
        "numpy batch forward: equivalent to pure-Python forward (native vs. fallback)",
        max_diff < 1e-9,
        f"max_diff={max_diff:.2e}",
    )

    softmax_model = MLP.random_init([4, 3], output_activation="softmax", seed=11)
    xs2 = [[rng.uniform(-1, 1) for _ in range(4)] for _ in range(10)]
    py2 = [softmax_model.forward(x) for x in xs2]
    np2 = ml_training.numpy_batch_forward(softmax_model, xs2)
    max_diff2 = max(abs(a - b) for ra, rb in zip(py2, np2) for a, b in zip(ra, rb))
    check("numpy batch forward: equivalent for softmax head too", max_diff2 < 1e-9, f"max_diff={max_diff2:.2e}")


def check_replay_buffer_reservoir_fairness():
    # Algorithm R guarantee: after n insertions into a capacity-k
    # buffer, the FIRST item inserted survives with probability
    # exactly k/n. Estimate this empirically over many independent
    # trials and check it lands close to the theoretical value --
    # this is the property lifelong learning's rehearsal depends on
    # (every era of a world's history stays representable, not just
    # the most recent one).
    capacity, n_insertions, trials = 10, 200, 3000
    expected_p = capacity / n_insertions
    survived = 0
    for trial in range(trials):
        buf = ReplayBuffer(capacity=capacity, seed=trial)
        for i in range(n_insertions):
            buf.add(i)
        if 0 in buf._items:
            survived += 1
    observed_p = survived / trials
    check(
        "replay buffer: reservoir sampling matches theoretical retention probability",
        abs(observed_p - expected_p) < 0.03,
        f"observed={observed_p:.4f} expected={expected_p:.4f}",
    )
    buf = ReplayBuffer(capacity=5, seed=1)
    for i in range(50):
        buf.add(i)
    check("replay buffer: stays bounded at capacity", len(buf) == 5, str(len(buf)))
    check("replay buffer: sample() never exceeds available items", len(buf.sample(100)) == 5)


def check_checkpoint_history():
    hist = CheckpointHistory(capacity=3)
    for tick in [10, 20, 30, 40]:
        hist.push(tick=tick, weights={"tick": tick}, metric=1.0 / tick)
    check("checkpoint history: bounded, oldest evicted", len(hist) == 3 and hist._entries[0].tick == 20)
    check("checkpoint history: latest() returns most recent", hist.latest().tick == 40)
    prev = hist.rollback()
    check("checkpoint history: rollback returns the prior checkpoint", prev is not None and prev.tick == 30)
    check("checkpoint history: rollback shrinks history", len(hist) == 2)

    empty = CheckpointHistory(capacity=3)
    check("checkpoint history: rollback on empty history is a safe no-op", empty.rollback() is None)


def check_shadow_gate():
    check("shadow gate: strictly better candidate passes", passes_shadow_gate(0.1, 0.2))
    check("shadow gate: worse candidate is rejected", not passes_shadow_gate(0.3, 0.2))
    check("shadow gate: within-tolerance wobble still passes", passes_shadow_gate(0.201, 0.2, tolerance=0.01))
    check("shadow gate: equal metric passes", passes_shadow_gate(0.2, 0.2))


def check_continual_learning_mitigates_forgetting():
    # Task A: y = x0. Task B: y = x1. A model pretrained on Task A
    # represents "a world's established mind, years into its life."
    # Continually retraining on fresh Task B data alone should degrade
    # Task A performance (catastrophic forgetting); continually
    # retraining WITH a replay buffer seeded from Task A should keep
    # Task A performance far more intact. This is the concrete
    # behavioural proof that L5's rehearsal mechanism does what it
    # claims, not just that the API runs without crashing.
    rng = random.Random(21)

    def make_examples(feature_index, n=150):
        exs = []
        for _ in range(n):
            x0 = rng.uniform(-1, 1)
            x1 = rng.uniform(-1, 1)
            y = x0 if feature_index == 0 else x1
            exs.append(ml_training.TrainingExample(x=[x0, x1], y=[y]))
        return exs

    task_a_train = make_examples(0)
    task_a_holdout = make_examples(0, n=60)
    task_b_train = make_examples(1)

    def fresh_pretrained_on_a():
        m = MLP.random_init([2, 6, 1], output_activation="linear", seed=5)
        ml_training.train_mlp_sgd(m, task_a_train, epochs=100, learning_rate=0.05, seed=5)
        return m

    # Note on learning_rate=0.01 below (not the 0.05 used elsewhere in
    # this file): mixing two orthogonal regression targets in one
    # combined batch is a harder optimization landscape for plain SGD
    # (no momentum/clipping) than either task alone -- 0.05 measurably
    # diverges to NaN here even though it converges cleanly for every
    # single-task check above. 0.01 is the stable, verified value.
    baseline_a_loss = ml_training.mean_loss(fresh_pretrained_on_a(), task_a_holdout)

    # Without replay: continual training on Task B alone.
    model_no_replay = fresh_pretrained_on_a()
    ml_training.continual_train_mlp(
        model_no_replay, task_b_train, replay_buffer=None, epochs=60, learning_rate=0.01, seed=6
    )
    forgotten_a_loss = ml_training.mean_loss(model_no_replay, task_a_holdout)

    # With replay: seed the buffer with Task A examples first, then
    # continually train on Task B with rehearsal.
    model_with_replay = fresh_pretrained_on_a()
    buf = ReplayBuffer(capacity=150, seed=2)
    for ex in task_a_train:
        buf.add(ex)
    ml_training.continual_train_mlp(
        model_with_replay, task_b_train, replay_buffer=buf, replay_fraction=1.0,
        epochs=60, learning_rate=0.01, seed=6,
    )
    rehearsed_a_loss = ml_training.mean_loss(model_with_replay, task_a_holdout)

    check(
        "continual learning: without replay, old-task performance measurably degrades",
        forgotten_a_loss > baseline_a_loss * 1.5,
        f"baseline={baseline_a_loss:.4f} forgotten={forgotten_a_loss:.4f}",
    )
    check(
        "continual learning: with replay, old-task performance stays much closer to baseline",
        rehearsed_a_loss < forgotten_a_loss * 0.5,
        f"forgotten={forgotten_a_loss:.4f} rehearsed={rehearsed_a_loss:.4f}",
    )

    # An untrained/constant-output model would score close to Var(y)
    # for y ~ Uniform(-1, 1), i.e. ~0.33 -- well below that means the
    # model genuinely learned Task B, not just avoided forgetting.
    new_task_b_holdout = make_examples(1, n=60)
    b_loss = ml_training.mean_loss(model_with_replay, new_task_b_holdout)
    check(
        "continual learning: model with replay still genuinely learns the new task",
        b_loss < 0.25,
        f"b_loss={b_loss:.4f}",
    )


def check_numpy_raises_cleanly_when_absent():
    if ml_training.HAS_NUMPY:
        print("[SKIP] numpy-absent RuntimeError check -- numpy IS installed in this environment")
        return
    model = MLP.random_init([2, 2], seed=1)
    raised = False
    try:
        ml_training.numpy_batch_forward(model, [[0.0, 0.0]])
    except RuntimeError:
        raised = True
    check("numpy batch forward: raises cleanly (not silently) when numpy absent", raised)


def main():
    check_encoder_basic()
    check_encoder_missing_and_bad_values()
    check_linear_layer_forward()
    check_mlp_forward_shapes_and_activations()
    check_weight_blob_round_trip()
    check_calibrator()
    check_sgd_trainer_reduces_loss()
    check_replay_buffer_reservoir_fairness()
    check_checkpoint_history()
    check_shadow_gate()
    check_continual_learning_mitigates_forgetting()
    check_numpy_equivalence()
    check_numpy_raises_cleanly_when_absent()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
