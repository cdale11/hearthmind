"""L0.2 -- model primitives: linear/logistic/small MLP + calibration.

Pure-Python inference always (stdlib only, the same fallback contract
every native `cpp/src/` module already honours) -- see `training.py`
for the offline-only numpy-accelerated path (v1.34.171). Weights are
versioned data (a small JSON blob), never code -- "ship learned
weights as data" per docs/ML-ARCHITECTURE-2026-08-01.md's L0.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass

WEIGHT_BLOB_SCHEMA_VERSION = 1


def sigmoid(x: float) -> float:
    # Numerically stable both sides of zero.
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def relu(x: float) -> float:
    return x if x > 0.0 else 0.0


def relu_grad(x: float) -> float:
    return 1.0 if x > 0.0 else 0.0


def dot(a, b) -> float:
    return sum(ai * bi for ai, bi in zip(a, b))


@dataclass
class LinearLayer:
    """One dense layer: y = W @ x + b. `weights` is (out_dim, in_dim)."""

    weights: list
    bias: list

    @property
    def in_dim(self) -> int:
        return len(self.weights[0]) if self.weights else 0

    @property
    def out_dim(self) -> int:
        return len(self.weights)

    def forward(self, x: list) -> list:
        return [dot(row, x) + b for row, b in zip(self.weights, self.bias)]

    def to_dict(self) -> dict:
        return {"weights": self.weights, "bias": self.bias}

    @classmethod
    def from_dict(cls, d: dict) -> "LinearLayer":
        return cls(weights=[list(row) for row in d["weights"]], bias=list(d["bias"]))

    @classmethod
    def random_init(cls, in_dim: int, out_dim: int, rng: random.Random, scale: float | None = None) -> "LinearLayer":
        s = scale if scale is not None else (1.0 / max(1, in_dim)) ** 0.5
        weights = [[rng.uniform(-s, s) for _ in range(in_dim)] for _ in range(out_dim)]
        bias = [0.0 for _ in range(out_dim)]
        return cls(weights=weights, bias=bias)


@dataclass
class MLP:
    """A 1-3 layer perceptron. Hidden layers use ReLU; the output
    activation is configurable ("linear"/"sigmoid"/"softmax") since
    different heads need different output shapes -- a scalar value
    head (L2.1) vs. a closed-class goal-policy head (L2.2)."""

    layers: list  # list[LinearLayer]
    output_activation: str = "linear"

    def forward(self, x: list) -> list:
        h = list(x)
        for i, layer in enumerate(self.layers):
            h = layer.forward(h)
            if i < len(self.layers) - 1:
                h = [relu(v) for v in h]
        if self.output_activation == "sigmoid":
            h = [sigmoid(v) for v in h]
        elif self.output_activation == "softmax":
            m = max(h) if h else 0.0
            exps = [math.exp(v - m) for v in h]
            s = sum(exps) or 1.0
            h = [v / s for v in exps]
        return h

    def to_dict(self) -> dict:
        return {
            "schema_version": WEIGHT_BLOB_SCHEMA_VERSION,
            "kind": "mlp",
            "output_activation": self.output_activation,
            "layers": [layer.to_dict() for layer in self.layers],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MLP":
        return cls(
            layers=[LinearLayer.from_dict(ld) for ld in d["layers"]],
            output_activation=d.get("output_activation", "linear"),
        )

    @classmethod
    def random_init(cls, dims: list, output_activation: str = "linear", seed: int = 0) -> "MLP":
        rng = random.Random(seed)
        layers = [
            LinearLayer.random_init(dims[i], dims[i + 1], rng)
            for i in range(len(dims) - 1)
        ]
        return cls(layers=layers, output_activation=output_activation)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f)

    @classmethod
    def load(cls, path: str) -> "MLP":
        with open(path) as f:
            d = json.load(f)
        if d.get("schema_version") != WEIGHT_BLOB_SCHEMA_VERSION:
            raise ValueError(f"unsupported weight blob schema_version={d.get('schema_version')!r}")
        return cls.from_dict(d)


@dataclass
class PlattCalibrator:
    """1D logistic calibration: maps a raw score to a calibrated
    probability via sigmoid(a*score + b). Deliberately NOT a network --
    L4.1's own guardrail: calibration is a solved statistical problem,
    an ANN here would be unnecessary generalization."""

    a: float = 1.0
    b: float = 0.0

    def calibrate(self, score: float) -> float:
        return sigmoid(self.a * score + self.b)

    def to_dict(self) -> dict:
        return {"schema_version": WEIGHT_BLOB_SCHEMA_VERSION, "kind": "platt", "a": self.a, "b": self.b}

    @classmethod
    def from_dict(cls, d: dict) -> "PlattCalibrator":
        return cls(a=d["a"], b=d["b"])

    def fit(self, scores: list, labels: list, epochs: int = 200, lr: float = 0.1) -> "PlattCalibrator":
        """Pure-Python 1D logistic-regression fit (gradient descent).
        Small enough that no numpy path is worth the complexity."""
        n = max(1, len(scores))
        for _ in range(epochs):
            grad_a = 0.0
            grad_b = 0.0
            for s, y in zip(scores, labels):
                p = self.calibrate(s)
                err = p - y
                grad_a += err * s
                grad_b += err
            self.a -= lr * grad_a / n
            self.b -= lr * grad_b / n
        return self
