"""L0.3 -- training harness: gradient descent over `primitives.MLP`.

Inference is always the pure-Python forward pass in `primitives.py`
(stdlib only, never a runtime dependency). Training may optionally use
numpy purely to accelerate a batch forward pass -- the same
computation, faster -- now that external libraries are permitted for
OFFLINE TRAINING ONLY (v1.34.171, explicit user directive; gated
behind the `ml` optional extra in `pyproject.toml`). numpy is never
required: everything here works with `HAS_NUMPY is False`, and
`scripts/verify_ml_substrate.py` proves the numpy-accelerated forward
pass is byte-for-byte equivalent (within floating tolerance) to the
pure-Python one it must match -- the same "native vs. fallback
equivalence" contract every `cpp/src/` module already carries.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from hearthmind.ml.primitives import MLP, relu, relu_grad, sigmoid

try:
    import numpy as _np
except ImportError:  # pragma: no cover - exercised when `ml` extra absent
    _np = None

HAS_NUMPY = _np is not None


@dataclass
class TrainingExample:
    x: list
    y: list


def mse_loss(pred: list, target: list) -> float:
    n = max(1, len(pred))
    return sum((p - t) ** 2 for p, t in zip(pred, target)) / n


def mean_loss(model: MLP, examples: list) -> float:
    if not examples:
        return 0.0
    total = 0.0
    for ex in examples:
        total += mse_loss(model.forward(ex.x), ex.y)
    return total / len(examples)


def train_mlp_sgd(
    model: MLP,
    examples: list,
    epochs: int = 50,
    learning_rate: float = 0.05,
    seed: int = 0,
) -> MLP:
    """Pure-Python full-backprop SGD (mean-squared-error loss), mutates
    `model` in place and returns it. Always correct, always available
    (no numpy needed) -- the reference implementation any accelerated
    path must match. Supports a "linear" or "sigmoid" output head
    (covers every L2/L4 use named in the architecture doc so far);
    softmax/cross-entropy backprop is out of scope for this first
    substrate slice."""
    rng = random.Random(seed)
    order = list(range(len(examples)))
    for _epoch in range(epochs):
        rng.shuffle(order)
        for idx in order:
            ex = examples[idx]
            _sgd_step(model, ex.x, ex.y, learning_rate)
    return model


def _sgd_step(model: MLP, x: list, y: list, lr: float) -> None:
    activations = [list(x)]
    pre_activations = []
    h = list(x)
    for i, layer in enumerate(model.layers):
        z = layer.forward(h)
        pre_activations.append(z)
        if i < len(model.layers) - 1:
            h = [relu(v) for v in z]
        elif model.output_activation == "sigmoid":
            h = [sigmoid(v) for v in z]
        else:
            h = list(z)
        activations.append(h)

    pred = activations[-1]
    n = max(1, len(pred))
    grad = [2.0 * (p - t) / n for p, t in zip(pred, y)]
    if model.output_activation == "sigmoid":
        grad = [g * p * (1.0 - p) for g, p in zip(grad, pred)]

    for layer_idx in range(len(model.layers) - 1, -1, -1):
        layer = model.layers[layer_idx]
        prev_activation = activations[layer_idx]
        if layer_idx < len(model.layers) - 1:
            z = pre_activations[layer_idx]
            grad = [g * relu_grad(zv) for g, zv in zip(grad, z)]

        for out_i in range(layer.out_dim):
            g = grad[out_i]
            row = layer.weights[out_i]
            for in_i in range(layer.in_dim):
                row[in_i] -= lr * g * prev_activation[in_i]
            layer.bias[out_i] -= lr * g

        if layer_idx > 0:
            next_grad = [0.0] * layer.in_dim
            for out_i in range(layer.out_dim):
                g = grad[out_i]
                row = layer.weights[out_i]
                for in_i in range(layer.in_dim):
                    next_grad[in_i] += g * row[in_i]
            grad = next_grad


def numpy_batch_forward(model: MLP, xs: list) -> list:
    """Numpy-accelerated batch forward pass -- the offline-training-time
    speed path (v1.34.171). Must produce results equivalent to calling
    `model.forward(x)` per-row in pure Python; raises if numpy isn't
    installed rather than silently falling back, since callers that
    explicitly asked for the accelerated path should know it wasn't
    available, not get a silently slower substitute."""
    if not HAS_NUMPY:
        raise RuntimeError("numpy is not installed -- install the 'ml' optional extra")
    h = _np.asarray(xs, dtype=_np.float64)
    for i, layer in enumerate(model.layers):
        w = _np.asarray(layer.weights, dtype=_np.float64)
        b = _np.asarray(layer.bias, dtype=_np.float64)
        h = h @ w.T + b
        if i < len(model.layers) - 1:
            h = _np.maximum(h, 0.0)
    if model.output_activation == "sigmoid":
        h = 1.0 / (1.0 + _np.exp(-h))
    elif model.output_activation == "softmax":
        m = _np.max(h, axis=1, keepdims=True)
        exps = _np.exp(h - m)
        h = exps / _np.sum(exps, axis=1, keepdims=True)
    return h.tolist()
