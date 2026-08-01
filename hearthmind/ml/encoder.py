"""L0.1 -- feature encoder: agent/settlement/world state -> a fixed
vector. Every model in Layer 1+ consumes the SAME encoded vector shape
for a given schema -- this is what prevents fragmentation (adding a
model is adding a head, not a pipeline) per
docs/ML-ARCHITECTURE-2026-08-01.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FeatureSchema:
    """An ordered, named list of numeric feature slots plus optional
    fixed-vocabulary categorical slots (one-hot). Deterministic
    ordering is the whole point -- the same schema always encodes the
    same field to the same vector index, across models and across
    training/inference."""

    numeric_fields: list
    categorical_fields: dict = field(default_factory=dict)  # name -> fixed vocab list

    def dim(self) -> int:
        return len(self.numeric_fields) + sum(len(v) for v in self.categorical_fields.values())

    def field_names(self) -> list:
        names = list(self.numeric_fields)
        for name, vocab in self.categorical_fields.items():
            names.extend(f"{name}={value}" for value in vocab)
        return names


class FeatureEncoder:
    """Encodes a plain dict of named values into a fixed-length vector
    per `schema`. A missing numeric field encodes as 0.0 (the same
    "absence means neutral" discipline `world/fields.py` already uses
    for its own field grids); an unrecognized categorical value simply
    fails to set any one-hot slot, rather than raising -- the encoder
    must never crash on unfamiliar input, since it will eventually see
    data that predates a schema's own vocabulary."""

    def __init__(self, schema: FeatureSchema):
        self.schema = schema

    def encode(self, values: dict) -> list:
        out = []
        for name in self.schema.numeric_fields:
            v = values.get(name, 0.0)
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                out.append(0.0)
        for name, vocab in self.schema.categorical_fields.items():
            chosen = values.get(name)
            out.extend(1.0 if chosen == option else 0.0 for option in vocab)
        return out
