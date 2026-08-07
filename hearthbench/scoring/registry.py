"""HearthBench A4.4 — the scorer registry.

A plain id -> `Scorer` map. Deliberately minimal: no plugin discovery,
no dynamic loading — a scorer is registered by an explicit Python call
(`register(scorer)`), same "no magic, an explicit call site you can
grep for" discipline every registry in this codebase already holds
(`hearthbench.adapters.registry.ADAPTER_REGISTRY`, `hearthmind.world.
ontology`'s concept registry). Duplicate `(id, version)` registration
is rejected outright — "scorer version is part of a run's identity"
only holds if two different formulas can never silently share one
version string.
"""
from __future__ import annotations

from hearthbench.scoring.types import Scorer


class DuplicateScorerError(ValueError):
    """Raised by `register()` when a scorer with the same `id` is
    already registered at a DIFFERENT version — the one case this
    registry actively guards against, since it would make "scorer
    version is part of a run's identity" a lie for that id. Re-
    registering the identical `(id, version)` pair is a safe no-op
    (idempotent module import), not an error."""


class ScorerRegistry:
    """A run resolves its `TestCase.scorers` (a list of string ids)
    against one of these — never against a bare Python import — so a
    stored run record's scorer list is meaningful without importing
    this package's internals."""

    def __init__(self) -> None:
        self._scorers: dict[str, Scorer] = {}

    def register(self, scorer: Scorer) -> None:
        existing = self._scorers.get(scorer.id)
        if existing is not None and existing.version != scorer.version:
            raise DuplicateScorerError(
                f"scorer {scorer.id!r} already registered at version "
                f"{existing.version!r}, cannot re-register at {scorer.version!r}"
            )
        self._scorers[scorer.id] = scorer

    def get(self, scorer_id: str) -> Scorer | None:
        return self._scorers.get(scorer_id)

    def resolve(self, scorer_ids: list) -> list:
        """Every registered scorer in `scorer_ids`, in order, silently
        dropping an unknown id — same "degrade, don't crash the run"
        discipline as `Scorer.score()` itself. A caller that needs to
        know about a missing id should diff `scorer_ids` against
        `[s.id for s in resolve(scorer_ids)]` itself."""
        return [self._scorers[sid] for sid in scorer_ids if sid in self._scorers]

    def all(self) -> list:
        return list(self._scorers.values())

    def by_tier(self, tier: int) -> list:
        return [s for s in self._scorers.values() if s.tier == tier]

    def ids(self) -> list:
        return list(self._scorers.keys())

    def __len__(self) -> int:
        return len(self._scorers)

    def __contains__(self, scorer_id: str) -> bool:
        return scorer_id in self._scorers
