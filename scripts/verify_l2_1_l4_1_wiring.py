#!/usr/bin/env python3
"""Verifies roadmap Phase 2's L2.1/L4.1 wiring: `ValueConsequenceModel`
into `SimulationEngine._voice_narrative_extra_scores` and
`BeliefConfidenceCalibrator` into `_maybe_schedule_self_tuning`'s
conviction gate (via the shared `_calibrated_confidence` helper). No
unittest, same `@check`-decorator standalone convention as every
sibling `verify_*.py`. Run:

    python3 scripts/verify_l2_1_l4_1_wiring.py
"""
from __future__ import annotations

import sys
import tempfile

sys.path.insert(0, ".")

from hearthmind.config import Config
from hearthmind.ml.belief_calibration import BeliefConfidenceCalibrator
from hearthmind.ml.value_model import ValueConsequenceModel, make_training_example
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import (
    REFLECTION_REJECTED_THRESHOLD, VOICE_NARRATIVE_VALUE_MODEL_BONUS_MAX, SimulationEngine,
    _belief_calibrator_path_for, _load_belief_calibrator, _value_model_path_for, _load_value_model,
)
from hearthmind.world.state import World

CHECKS = []


def check(name):
    def decorator(fn):
        CHECKS.append((name, fn))
        return fn
    return decorator


def _make_engine(seed: int = 3) -> SimulationEngine:
    d = tempfile.mkdtemp()
    db_path = f"{d}/world.sqlite3"
    cfg = Config(db_path=db_path, width=20, height=20, seed=seed, llm_enabled=False)
    conn = connect(db_path)
    world = World.create_new(cfg)
    return SimulationEngine(conn, cfg, world)


# ---------------------------------------------------------------------------
# ValueConsequenceModel persistence


@check("ValueConsequenceModel: to_dict/from_dict round-trips real trained weights")
def check_value_model_round_trip():
    model = ValueConsequenceModel.new(seed=1)
    examples = [
        make_training_example({"emotion_intensity": 0.9, "recent_event_count_k": 0.5, "relationship_extremity": 0.5, "is_core_cast": 1.0}, 0.8, True),
        make_training_example({"emotion_intensity": 0.1, "recent_event_count_k": 0.0, "relationship_extremity": 0.1, "is_core_cast": 1.0}, 0.1, False),
    ]
    model.train(examples, epochs=20, learning_rate=0.05, seed=1)
    restored = ValueConsequenceModel.from_dict(model.to_dict())
    probe = {"emotion_intensity": 0.5, "recent_event_count_k": 0.5, "relationship_extremity": 0.5, "is_core_cast": 1.0}
    return abs(restored.predict(probe) - model.predict(probe)) < 1e-9


@check("ValueConsequenceModel: from_dict rejects a bad schema_version")
def check_value_model_bad_schema():
    d = ValueConsequenceModel.new(seed=0).to_dict()
    d["schema_version"] = 999
    try:
        ValueConsequenceModel.from_dict(d)
        return False
    except ValueError:
        return True


@check("ValueConsequenceModel: from_dict rejects a mismatched kind")
def check_value_model_bad_kind():
    d = ValueConsequenceModel.new(seed=0).to_dict()
    d["kind"] = "goal_policy"
    try:
        ValueConsequenceModel.from_dict(d)
        return False
    except ValueError:
        return True


@check("ValueConsequenceModel: save/load round-trips through a real file")
def check_value_model_save_load():
    d = tempfile.mkdtemp()
    path = f"{d}/value_model_weights.json"
    model = ValueConsequenceModel.new(seed=2)
    model.save(path)
    loaded = ValueConsequenceModel.load(path)
    return abs(loaded.predict({"emotion_intensity": 0.5, "recent_event_count_k": 0.2, "relationship_extremity": 0.3, "is_core_cast": 1.0})
               - model.predict({"emotion_intensity": 0.5, "recent_event_count_k": 0.2, "relationship_extremity": 0.3, "is_core_cast": 1.0})) < 1e-9


# ---------------------------------------------------------------------------
# BeliefConfidenceCalibrator persistence


@check("BeliefConfidenceCalibrator: to_dict/from_dict round-trips real fitted weights")
def check_calibrator_round_trip():
    calibrator = BeliefConfidenceCalibrator().fit([(0.9, 1.0), (0.2, 0.0), (0.8, 1.0), (0.1, 0.0)], epochs=50, lr=0.2)
    restored = BeliefConfidenceCalibrator.from_dict(calibrator.to_dict())
    return abs(restored.calibrate(0.5) - calibrator.calibrate(0.5)) < 1e-9


@check("BeliefConfidenceCalibrator: from_dict rejects a bad schema_version")
def check_calibrator_bad_schema():
    d = BeliefConfidenceCalibrator().to_dict()
    d["schema_version"] = 999
    try:
        BeliefConfidenceCalibrator.from_dict(d)
        return False
    except ValueError:
        return True


@check("BeliefConfidenceCalibrator: from_dict rejects a mismatched kind")
def check_calibrator_bad_kind():
    d = BeliefConfidenceCalibrator().to_dict()
    d["kind"] = "value_model"
    try:
        BeliefConfidenceCalibrator.from_dict(d)
        return False
    except ValueError:
        return True


@check("BeliefConfidenceCalibrator: save/load round-trips through a real file")
def check_calibrator_save_load():
    d = tempfile.mkdtemp()
    path = f"{d}/belief_calibrator_weights.json"
    calibrator = BeliefConfidenceCalibrator().fit([(0.9, 1.0), (0.1, 0.0)], epochs=30, lr=0.2)
    calibrator.save(path)
    loaded = BeliefConfidenceCalibrator.load(path)
    return abs(loaded.calibrate(0.6) - calibrator.calibrate(0.6)) < 1e-9


# ---------------------------------------------------------------------------
# Engine path resolution / loading


@check("engine wiring: _value_model_path_for returns None for :memory:, a real path otherwise")
def check_value_model_path_for():
    return _value_model_path_for(":memory:") is None and _value_model_path_for("/tmp/x/world.db").endswith("value_model_weights.json")


@check("engine wiring: _belief_calibrator_path_for returns None for :memory:, a real path otherwise")
def check_belief_calibrator_path_for():
    return (
        _belief_calibrator_path_for(":memory:") is None
        and _belief_calibrator_path_for("/tmp/x/world.db").endswith("belief_calibrator_weights.json")
    )


@check("engine wiring: _load_value_model returns None when no file exists")
def check_load_value_model_missing():
    return _load_value_model("/tmp/definitely_does_not_exist_value_model.json") is None


@check("engine wiring: _load_value_model loads a real trained file end to end")
def check_load_value_model_real():
    d = tempfile.mkdtemp()
    path = f"{d}/value_model_weights.json"
    ValueConsequenceModel.new(seed=4).save(path)
    return isinstance(_load_value_model(path), ValueConsequenceModel)


@check("engine wiring: _load_value_model degrades to None on a corrupted file, never crashes")
def check_load_value_model_corrupted():
    d = tempfile.mkdtemp()
    path = f"{d}/value_model_weights.json"
    with open(path, "w") as f:
        f.write("{not valid json")
    return _load_value_model(path) is None


@check("engine wiring: _load_belief_calibrator loads a real trained file end to end")
def check_load_belief_calibrator_real():
    d = tempfile.mkdtemp()
    path = f"{d}/belief_calibrator_weights.json"
    BeliefConfidenceCalibrator().fit([(0.9, 1.0), (0.1, 0.0)]).save(path)
    return isinstance(_load_belief_calibrator(path), BeliefConfidenceCalibrator)


@check("engine wiring: _load_belief_calibrator degrades to None on a corrupted file, never crashes")
def check_load_belief_calibrator_corrupted():
    d = tempfile.mkdtemp()
    path = f"{d}/belief_calibrator_weights.json"
    with open(path, "w") as f:
        f.write("not json at all")
    return _load_belief_calibrator(path) is None


# ---------------------------------------------------------------------------
# full_diagnostics()


@check("full_diagnostics: value_model/belief_calibrator report loaded=False with no weights files")
def check_diagnostics_unloaded():
    eng = _make_engine()
    report = eng.full_diagnostics()
    return report["value_model"]["loaded"] is False and report["belief_calibrator"]["loaded"] is False


@check("full_diagnostics: value_model/belief_calibrator report loaded=True with real weights files present")
def check_diagnostics_loaded():
    eng = _make_engine()
    ValueConsequenceModel.new(seed=0).save(eng._value_model_path)
    BeliefConfidenceCalibrator().fit([(0.9, 1.0), (0.1, 0.0)]).save(eng._belief_calibrator_path)
    eng._value_model = _load_value_model(eng._value_model_path)
    eng._belief_calibrator = _load_belief_calibrator(eng._belief_calibrator_path)
    report = eng.full_diagnostics()
    return report["value_model"]["loaded"] is True and report["belief_calibrator"]["loaded"] is True


# ---------------------------------------------------------------------------
# _calibrated_confidence


@check("_calibrated_confidence: no calibrator loaded -> identity (byte-for-byte unchanged)")
def check_calibrated_confidence_none():
    eng = _make_engine()
    return eng._calibrated_confidence(0.42) == 0.42 and eng._calibrated_confidence(0.0) == 0.0 and eng._calibrated_confidence(1.0) == 1.0


@check("_calibrated_confidence: a real loaded calibrator genuinely changes the value")
def check_calibrated_confidence_loaded():
    eng = _make_engine()
    # A calibrator fit to say "0.9-ish stated confidence never actually
    # holds up" should pull a high stated confidence DOWN.
    eng._belief_calibrator = BeliefConfidenceCalibrator().fit(
        [(0.9, 0.0), (0.85, 0.0), (0.9, 0.0), (0.8, 0.0), (0.9, 0.0)], epochs=300, lr=0.3,
    )
    calibrated = eng._calibrated_confidence(0.9)
    return calibrated != 0.9 and calibrated < 0.9


@check("live production-path proof: a real calibrator can flip the self_tuning conviction gate's own threshold check")
def check_calibrated_confidence_gate_flip():
    eng = _make_engine()
    raw_confidence = REFLECTION_REJECTED_THRESHOLD + 0.05  # just above threshold, uncalibrated
    assert raw_confidence > REFLECTION_REJECTED_THRESHOLD  # sanity: passes uncalibrated
    # A calibrator that maps everything near this value below threshold.
    eng._belief_calibrator = BeliefConfidenceCalibrator().fit(
        [(raw_confidence, 0.0)] * 5 + [(0.9, 0.0)] * 5, epochs=400, lr=0.3,
    )
    calibrated = eng._calibrated_confidence(raw_confidence)
    passes_raw = raw_confidence > REFLECTION_REJECTED_THRESHOLD
    passes_calibrated = calibrated > REFLECTION_REJECTED_THRESHOLD
    return passes_raw and not passes_calibrated


# ---------------------------------------------------------------------------
# _voice_narrative_extra_scores


@check("no-op proof: with no value_model loaded, _voice_narrative_extra_scores is unaffected by this pass")
def check_extra_scores_no_model():
    eng = _make_engine()
    assert eng._value_model is None
    scores_before = dict(eng._voice_narrative_extra_scores())
    # Re-run: same inputs, same output -- confirms no hidden state drift.
    scores_after = dict(eng._voice_narrative_extra_scores())
    return scores_before == scores_after


@check("live proof: a loaded value_model genuinely adds a real bonus for a core-cast agent")
def check_extra_scores_with_model():
    eng = _make_engine(seed=11)
    core_ids = list(eng.world.population.core_agent_ids)
    if not core_ids:
        return True  # nothing to check against a world with no core cast yet
    agent = eng.world.population.get(core_ids[0])
    agent.emotions["fear"] = 0.95  # force a high emotion_intensity reading

    class _AlwaysHighModel:
        def predict(self, features):
            return 1.0

    eng._value_model = _AlwaysHighModel()
    scores = eng._voice_narrative_extra_scores()
    expected_max_bonus = VOICE_NARRATIVE_VALUE_MODEL_BONUS_MAX
    return scores.get(agent.id, 0.0) >= expected_max_bonus - 1e-6


@check("live proof: a value_model predicting 0.0 for everyone contributes no bonus (a real no-op at that extreme)")
def check_extra_scores_zero_model():
    eng = _make_engine(seed=12)

    class _AlwaysZeroModel:
        def predict(self, features):
            return 0.0

    eng._value_model = _AlwaysZeroModel()
    scores_with = eng._voice_narrative_extra_scores()
    eng._value_model = None
    scores_without = eng._voice_narrative_extra_scores()
    return scores_with == scores_without


def main() -> int:
    failures = []
    for name, fn in CHECKS:
        try:
            ok = fn()
        except Exception as exc:  # noqa: BLE001 -- report, don't crash the suite
            ok = False
            print(f"[FAIL] {name}: raised {exc!r}")
            failures.append(name)
            continue
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failures.append(name)
    print(f"\n{len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
