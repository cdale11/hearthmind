#!/usr/bin/env python3
"""Verifies `hearthmind.ml.law_scorer.LawCandidateScorer` -- the
dynamic-candidate-set mechanism for `llm/laws.py`'s "which hardship
becomes a law" (docs/ROADMAP-2026-07-REMAINING.md, the last flagged
Phase-1 site, deliberately excluded from `hearthmind.ml.decision_
policy`'s four fixed-class sites since it's a genuinely different
ranking/scoring problem shape -- see that module's own docstring).

No unittest, same `@check`-decorator standalone convention as
`scripts/verify_decision_policies_wiring.py`. Run:
    python3 scripts/verify_law_scorer_wiring.py
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile

sys.path.insert(0, ".")

from hearthmind.cognition.pillar import default_village_pillar
from hearthmind.ml.law_scorer import (
    LAW_OCCURRENCE_CAP, LawCandidateScorer, build_training_examples, encode_candidate,
)
from hearthmind.simulation.engine import SimulationEngine, _law_scorer_path_for, _load_law_scorer

CHECKS = []


def check(name):
    def decorator(fn):
        CHECKS.append((name, fn))
        return fn
    return decorator


class _FakeWorld:
    def __init__(self):
        self.village_pillar = default_village_pillar()


class _FakeEngine:
    """Stands in for `SimulationEngine` so `_law_candidate_score` (a
    real bound method, called unbound below) can be exercised without
    constructing a full engine/world/DB -- it only ever touches
    `self.world.village_pillar` and `self._law_scorer`."""

    def __init__(self, law_scorer=None):
        self.world = _FakeWorld()
        self._law_scorer = law_scorer


def _score_fn(engine):
    return SimulationEngine._law_candidate_score.__get__(engine)


def _trained_scorer(seed=0):
    scorer = LawCandidateScorer(seed=seed)
    examples = build_training_examples(
        [(1, 0.0, False)] * 20 + [(60, 0.9, True)] * 20,
        [False] * 20 + [True] * 20,
    )
    rng = random.Random(seed)
    shuffled = list(examples)
    rng.shuffle(shuffled)
    scorer.learn(shuffled[:32], shuffled[32:], tick=0, epochs=200, learning_rate=0.05, seed=seed)
    return scorer


@check("LawCandidateScorer: to_dict/from_dict round-trips real trained weights")
def _():
    scorer = _trained_scorer()
    restored = LawCandidateScorer.from_dict(scorer.to_dict())
    assert abs(restored.score(5, 0.5) - scorer.score(5, 0.5)) < 1e-9


@check("LawCandidateScorer: from_dict rejects a bad schema_version")
def _():
    scorer = LawCandidateScorer(seed=1)
    d = scorer.to_dict()
    d["schema_version"] = 999
    try:
        LawCandidateScorer.from_dict(d)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


@check("LawCandidateScorer: from_dict rejects a mismatched kind")
def _():
    scorer = LawCandidateScorer(seed=1)
    d = scorer.to_dict()
    d["kind"] = "goal_policy"
    try:
        LawCandidateScorer.from_dict(d)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


@check("LawCandidateScorer: save/load round-trips through a real file")
def _():
    scorer = _trained_scorer(seed=2)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        scorer.save(path)
        restored = LawCandidateScorer.load(path)
        assert abs(restored.score(10, 0.2) - scorer.score(10, 0.2)) < 1e-9


@check("encode_candidate: a huge occurrence count is capped, not fed raw")
def _():
    x = encode_candidate(occurrences=10000, pillar_confidence=1.0, initiated_by_conviction=True)
    assert x[0] == LAW_OCCURRENCE_CAP


@check("encode_candidate: absent signal encodes to zero")
def _():
    assert encode_candidate(occurrences=0, pillar_confidence=0.0, initiated_by_conviction=False) == [0.0, 0.0, 0.0]


@check("LawCandidateScorer.rank: orders a real trained pattern correctly")
def _():
    scorer = _trained_scorer(seed=3)
    candidates = [("low", 1, 0.0, False), ("high", 60, 0.9, True)]
    assert scorer.rank(candidates)[0] == "high"


@check("LawCandidateScorer.rank: stable on a genuine tie")
def _():
    scorer = LawCandidateScorer(seed=4)
    candidates = [("a", 5, 0.5, False), ("b", 5, 0.5, False)]
    assert scorer.rank(candidates) == ["a", "b"]


@check("LawCandidateScorer.learn: measurably separates a low-pressure and a high-pressure pattern")
def _():
    scorer = _trained_scorer(seed=5)
    assert scorer.score(1, 0.0, False) < scorer.score(60, 0.9, True)


@check("engine wiring: _law_candidate_score returns a constant 0.0 for every candidate with no scorer loaded")
def _():
    engine = _FakeEngine(law_scorer=None)
    method = _score_fn(engine)
    assert method("theft", 5, False) == 0.0
    assert method("family_extinction", 500, True) == 0.0


@check("engine wiring: _law_candidate_score consults a real loaded scorer")
def _():
    scorer = _trained_scorer(seed=6)
    engine = _FakeEngine(law_scorer=scorer)
    method = _score_fn(engine)
    confidence = engine.world.village_pillar.subject_confidence("theft")
    assert abs(method("theft", 60, True) - scorer.score(60, confidence, True)) < 1e-9


@check("candidate pick: byte-identical to the pre-scorer two-key max() when no scorer is loaded (no-op proof)")
def _():
    engine = _FakeEngine(law_scorer=None)
    method = _score_fn(engine)
    pillar = engine.world.village_pillar
    candidates = {"theft": 5, "dispute_feud": 5, "materials_bottleneck": 3}
    expected = max(candidates, key=lambda k: (candidates[k], pillar.subject_confidence(k)))
    actual = max(candidates, key=lambda k: (candidates[k], pillar.subject_confidence(k), method(k, candidates[k], False)))
    assert actual == expected


@check("candidate pick: a real trained scorer CAN break a genuine tie (proof the wiring is live)")
def _():
    scorer = _trained_scorer(seed=9)
    engine = _FakeEngine(law_scorer=scorer)
    method = _score_fn(engine)
    tied = {"low_conv": 5, "high_conv": 5}
    conv_map = {"low_conv": False, "high_conv": True}
    picked = max(tied, key=lambda k: (tied[k], 0.0, method(k, tied[k], conv_map[k])))
    assert picked == "high_conv"


@check("engine wiring: _law_scorer_path_for returns None for :memory:, a real path otherwise")
def _():
    assert _law_scorer_path_for(":memory:") is None
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "world.db")
        assert _law_scorer_path_for(db_path) == os.path.join(tmpdir, "law_scorer_weights.json")


@check("engine wiring: _load_law_scorer returns None when no file exists")
def _():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "law_scorer_weights.json")
        assert _load_law_scorer(path) is None
        assert _load_law_scorer(None) is None


@check("engine wiring: _load_law_scorer loads a real trained file end to end")
def _():
    scorer = _trained_scorer(seed=8)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "law_scorer_weights.json")
        scorer.save(path)
        loaded = _load_law_scorer(path)
        assert loaded is not None
        assert abs(loaded.score(30, 0.4) - scorer.score(30, 0.4)) < 1e-9


@check("engine wiring: _load_law_scorer degrades to None on a corrupted file, never crashes")
def _():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "law_scorer_weights.json")
        with open(path, "w") as f:
            f.write("{not valid json")
        assert _load_law_scorer(path) is None


@check("training script: end-to-end synthetic archive -> trains and saves real weights")
def _():
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_dir = os.path.join(tmpdir, "archive", "laws")
        os.makedirs(archive_dir, exist_ok=True)
        lines = []
        for _ in range(15):
            lines.append(json.dumps({
                "task": "laws", "fallback_used": False,
                "layer1_structured_input": {"occurrences": 1, "pillar_confidence": 0.1, "initiated_by_conviction": False},
                "layer4_parsed_output": {"forms": False},
            }))
        for _ in range(15):
            lines.append(json.dumps({
                "task": "laws", "fallback_used": False,
                "layer1_structured_input": {"occurrences": 60, "pillar_confidence": 0.9, "initiated_by_conviction": True},
                "layer4_parsed_output": {"forms": True, "text": "a real law", "kind": "law"},
            }))
        with open(os.path.join(archive_dir, "2026-01-01.jsonl"), "w") as f:
            f.write("\n".join(lines))
        out_dir = os.path.join(tmpdir, "out")
        result = subprocess.run(
            [sys.executable, "scripts/train_law_scorer_from_archive.py",
             "--archive-dir", os.path.join(tmpdir, "archive"), "--out-dir", out_dir],
            capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        out_path = os.path.join(out_dir, "law_scorer_weights.json")
        assert os.path.exists(out_path), result.stdout
        loaded = LawCandidateScorer.load(out_path)
        assert loaded is not None


@check("training script: a fallback_used=True example is never used as a real pair")
def _():
    with tempfile.TemporaryDirectory() as tmpdir:
        archive_dir = os.path.join(tmpdir, "archive", "laws")
        os.makedirs(archive_dir, exist_ok=True)
        lines = [json.dumps({
            "task": "laws", "fallback_used": True,
            "layer1_structured_input": {"occurrences": 1, "pillar_confidence": 0.1, "initiated_by_conviction": False},
            "layer4_parsed_output": {"forms": False},
        }) for _ in range(30)]
        with open(os.path.join(archive_dir, "2026-01-01.jsonl"), "w") as f:
            f.write("\n".join(lines))
        out_dir = os.path.join(tmpdir, "out")
        result = subprocess.run(
            [sys.executable, "scripts/train_law_scorer_from_archive.py",
             "--archive-dir", os.path.join(tmpdir, "archive"), "--out-dir", out_dir],
            capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert not os.path.exists(os.path.join(out_dir, "law_scorer_weights.json"))


def main():
    failures = []
    for name, fn in CHECKS:
        try:
            fn()
            print(f"[PASS] {name}")
        except Exception as exc:  # noqa: BLE001
            failures.append((name, exc))
            print(f"[FAIL] {name}: {exc}")
    print(f"\n{len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed.")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
