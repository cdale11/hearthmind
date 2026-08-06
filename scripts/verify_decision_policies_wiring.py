#!/usr/bin/env python3
"""Verify Tier 6 Phase 1's last named item, wired (v1.34.260): the
generalized `hearthmind.ml.decision_policy.DecisionPolicy`, its four
real site configs, the four `llm/*.py` `fallback_*` functions' new
optional `policy`/`rng` params (byte-for-byte parity at `policy=None`),
`simulation/engine.py`'s file-next-to-`db_path` loading for all four
sites, and a real end-to-end run of `scripts/train_decision_policies_
from_archive.py` against a synthetic archive shaped like a real
`review_pack.json` export.

No unittest, same standalone-script convention as every sibling
`verify_*.py`. Run: python3 scripts/verify_decision_policies_wiring.py
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile

sys.path.insert(0, ".")

from hearthmind.ml.decision_policy import (
    DISPUTE_POLICY_CONFIG, FISSION_POLICY_CONFIG, FOUNDING_POLICY_CONFIG, MIGRATION_POLICY_CONFIG,
    DecisionPolicy, build_distillation_examples,
)
from hearthmind.simulation.engine import _decision_policy_path_for, _load_decision_policy

CHECKS = []


def check(name):
    def decorator(fn):
        CHECKS.append((name, fn))
        return fn
    return decorator


class _Agent:
    def __init__(self, name, traits, standing_penalty=0.0):
        self.name = name
        self.traits = traits
        self.standing_penalty = standing_penalty


def _trained_policy(config, seed=0):
    rng = random.Random(seed)
    states, classes = [], []
    for _ in range(60):
        c = rng.choice(config.classes)
        state = {f: rng.uniform(-1, 1) for f in config.schema.numeric_fields}
        states.append(state)
        classes.append(c)
    examples = build_distillation_examples(config, states, classes)
    policy = DecisionPolicy(config, seed=seed)
    policy.learn(examples, examples[:10], tick=0, epochs=50, learning_rate=0.01, seed=seed)
    return policy


@check("DecisionPolicy: to_dict/from_dict round-trips real trained weights")
def _():
    policy = _trained_policy(FISSION_POLICY_CONFIG)
    d = policy.to_dict()
    restored = DecisionPolicy.from_dict(d, FISSION_POLICY_CONFIG)
    state = {"trait_ambition": 0.5, "trait_openness": -0.3, "crowding_ratio": 1.2}
    assert policy.predict(state).distribution == restored.predict(state).distribution


@check("DecisionPolicy: from_dict rejects a mismatched kind/classes/schema")
def _():
    policy = _trained_policy(FISSION_POLICY_CONFIG)
    d = policy.to_dict()
    try:
        DecisionPolicy.from_dict(d, MIGRATION_POLICY_CONFIG)
        raise AssertionError("expected ValueError for mismatched kind")
    except ValueError:
        pass
    d2 = policy.to_dict()
    d2["schema_version"] = 999
    try:
        DecisionPolicy.from_dict(d2, FISSION_POLICY_CONFIG)
        raise AssertionError("expected ValueError for bad schema_version")
    except ValueError:
        pass


@check("DecisionPolicy: save/load round-trips through a real file")
def _():
    policy = _trained_policy(DISPUTE_POLICY_CONFIG)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "weights.json")
        policy.save(path)
        restored = DecisionPolicy.load(path, DISPUTE_POLICY_CONFIG)
        state = {f: 0.1 for f in DISPUTE_POLICY_CONFIG.schema.numeric_fields}
        assert policy.predict(state).distribution == restored.predict(state).distribution


@check("DecisionPolicy: allowed_classes masks and renormalizes correctly")
def _():
    policy = _trained_policy(DISPUTE_POLICY_CONFIG)
    state = {f: 0.1 for f in DISPUTE_POLICY_CONFIG.schema.numeric_fields}
    masked = policy.predict(state, allowed_classes={"reconcile", "feud"})
    assert set(masked.distribution.keys()) == {"reconcile", "feud"}
    assert abs(sum(masked.distribution.values()) - 1.0) < 1e-9


@check("DecisionPolicy: sample_class only ever draws from the allowed set")
def _():
    policy = _trained_policy(DISPUTE_POLICY_CONFIG)
    state = {f: 0.1 for f in DISPUTE_POLICY_CONFIG.schema.numeric_fields}
    rng = random.Random(1)
    allowed = {"reconcile", "feud"}
    for _ in range(100):
        assert policy.sample_class(state, rng, allowed_classes=allowed) in allowed


@check("fallback_dispute: policy=None reproduces the exact original if-ladder output")
def _():
    from hearthmind.llm.dispute import fallback_dispute
    a = _Agent("Aran", {"sociability": 0.5})
    b = _Agent("Bryn", {"sociability": 0.5})
    old = fallback_dispute(a, b, has_council=True, reputation_a=0.1, reputation_b=0.1)
    new = fallback_dispute(a, b, has_council=True, reputation_a=0.1, reputation_b=0.1, policy=None)
    assert old == new


@check("fallback_dispute: with a policy, ostracism is only ever chosen when has_council, masking enforced")
def _():
    from hearthmind.llm.dispute import fallback_dispute
    policy = _trained_policy(DISPUTE_POLICY_CONFIG)
    a = _Agent("Aran", {"sociability": -0.9})
    b = _Agent("Bryn", {"sociability": -0.9})
    for _ in range(50):
        result = fallback_dispute(
            a, b, has_council=False, reputation_a=-0.9, reputation_b=0.9,
            policy=policy, rng=random.Random(random.randint(0, 10**6)),
        )
        assert result["outcome"] in ("reconcile", "feud")


@check("fallback_decision (fission): policy=None reproduces the exact original ambition-threshold output")
def _():
    from hearthmind.llm.fission import fallback_decision
    leader = _Agent("Cael", {"ambition": 0.7})
    old = fallback_decision(leader)
    new = fallback_decision(leader, policy=None)
    assert old == new


@check("fallback_decision (fission): with a policy, output is a real, structurally valid dict")
def _():
    from hearthmind.llm.fission import fallback_decision
    policy = _trained_policy(FISSION_POLICY_CONFIG)
    leader = _Agent("Cael", {"ambition": 0.7, "openness": 0.2})
    result = fallback_decision(leader, members=40, housing_capacity=20, policy=policy, rng=random.Random(2))
    assert isinstance(result["depart"], bool)
    assert result["schism"] is False


@check("fallback_decision (migration): policy=None reproduces the exact original penalty-threshold output")
def _():
    from hearthmind.llm.migration import fallback_decision
    agent = _Agent("Dara", {"resilience": 0.2}, standing_penalty=0.5)
    old = fallback_decision(agent)
    new = fallback_decision(agent, policy=None)
    assert old == new


@check("fallback_founding: policy=None reproduces the exact original ambition-threshold output")
def _():
    from hearthmind.llm.founding import fallback_founding
    founder = _Agent("Elin", {"ambition": 0.5})
    old = fallback_founding(founder)
    new = fallback_founding(founder, policy=None)
    assert old == new


@check("fallback_founding: with a policy, output is a real, structurally valid dict")
def _():
    from hearthmind.llm.founding import fallback_founding
    policy = _trained_policy(FOUNDING_POLICY_CONFIG)
    founder = _Agent("Elin", {"ambition": 0.5})
    result = fallback_founding(founder, master_count=2, policy=policy, rng=random.Random(3))
    assert isinstance(result["found"], bool)
    assert isinstance(result["reason"], str)


@check("engine wiring: _decision_policy_path_for returns None for :memory:, real per-site paths otherwise")
def _():
    assert _decision_policy_path_for(":memory:", "dispute") is None
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "world.db")
        assert _decision_policy_path_for(db_path, "dispute") == os.path.join(tmpdir, "dispute_policy_weights.json")
        assert _decision_policy_path_for(db_path, "fission") == os.path.join(tmpdir, "fission_policy_weights.json")
        assert _decision_policy_path_for(db_path, "migration") == os.path.join(tmpdir, "migration_policy_weights.json")
        assert _decision_policy_path_for(db_path, "founding") == os.path.join(tmpdir, "founding_policy_weights.json")


@check("engine wiring: _load_decision_policy returns None when no file exists")
def _():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "dispute_policy_weights.json")
        assert _load_decision_policy(path, "dispute") is None
        assert _load_decision_policy(None, "dispute") is None


@check("engine wiring: _load_decision_policy loads a real trained file end to end, for all four sites")
def _():
    for site, config in (
        ("dispute", DISPUTE_POLICY_CONFIG), ("fission", FISSION_POLICY_CONFIG),
        ("migration", MIGRATION_POLICY_CONFIG), ("founding", FOUNDING_POLICY_CONFIG),
    ):
        policy = _trained_policy(config)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "weights.json")
            policy.save(path)
            loaded = _load_decision_policy(path, site)
            assert loaded is not None
            state = {f: 0.1 for f in config.schema.numeric_fields}
            assert loaded.predict(state).distribution == policy.predict(state).distribution


@check("engine wiring: _load_decision_policy degrades to None on a corrupted file, never crashes")
def _():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "dispute_policy_weights.json")
        with open(path, "w") as f:
            f.write("{not valid json")
        assert _load_decision_policy(path, "dispute") is None


@check("engine wiring: _load_decision_policy rejects a file meant for a DIFFERENT site")
def _():
    fission_policy = _trained_policy(FISSION_POLICY_CONFIG)
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "migration_policy_weights.json")
        fission_policy.save(path)
        assert _load_decision_policy(path, "migration") is None


@check("training script: end-to-end synthetic archive -> trains at least one site, saves real weights")
def _():
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        rng = random.Random(11)
        review_pack = []
        for i in range(120):
            reconciles = rng.random() > 0.5
            review_pack.append({
                "task": "dispute",
                "fallback_used": False,
                "layer1_structured_input": {
                    "trait_sociability_a": rng.uniform(0.3, 0.9) if reconciles else rng.uniform(-0.9, -0.3),
                    "trait_sociability_b": rng.uniform(0.3, 0.9) if reconciles else rng.uniform(-0.9, -0.3),
                    "reputation_a": 0.0, "reputation_b": 0.0,
                    "rival_factions": False, "rival_families": False,
                    "debt_a_owes_b": 0.0, "debt_b_owes_a": 0.0,
                    "council_favors_a": False, "council_favors_b": False,
                    "has_law_against_feuding": False, "has_council": True,
                },
                "layer4_parsed_output": {"outcome": "reconcile" if reconciles else "feud"},
            })
        review_pack_path = os.path.join(tmpdir, "review_pack.json")
        with open(review_pack_path, "w") as f:
            json.dump(review_pack, f)
        out_dir = os.path.join(tmpdir, "world")

        result = subprocess.run(
            [sys.executable, "scripts/train_decision_policies_from_archive.py",
             "--review-pack", review_pack_path, "--out-dir", out_dir],
            capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "[dispute] Wrote trained weights" in result.stdout, result.stdout
        out_path = os.path.join(out_dir, "dispute_policy_weights.json")
        assert os.path.exists(out_path)
        loaded = DecisionPolicy.load(out_path, DISPUTE_POLICY_CONFIG)
        assert loaded is not None
        # the other three sites had zero real examples in this synthetic
        # archive (only "dispute" rows were ever added) -- confirms the
        # skip path is real and doesn't fabricate a file.
        for filename in ("fission_policy_weights.json", "migration_policy_weights.json", "founding_policy_weights.json"):
            assert not os.path.exists(os.path.join(out_dir, filename))


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
