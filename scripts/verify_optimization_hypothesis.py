#!/usr/bin/env python3
"""Standalone verification for B13 (Optimization hypotheses,
docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B). Same convention as
every sibling scripts/verify_*.py: no unittest, no CI pipeline, run
manually.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from hearthmind.simulation.optimization_hypothesis import (
    AdaptationHistory,
    AdaptationRecord,
    CrossAuthorityError,
    HypothesisLoop,
    ADAPTATION_HISTORY_MAX,
)
from hearthmind.simulation.tuning import SafetyClass, Tunable, TunableRegistry

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


LOWER_IS_BETTER = lambda before, after: after < before


def _fresh_registry():
    registry = TunableRegistry()
    registry.register(Tunable(
        name="safe_tunable", value=10.0, min_value=0.0, max_value=100.0, step=1.0,
        safety_class=SafetyClass.SAFE,
    ))
    registry.register(Tunable(
        name="sensitive_tunable", value=2.0, min_value=1.0, max_value=8.0, step=1.0,
        safety_class=SafetyClass.SENSITIVE, description="synthetic fixture for this verify script's own checks.",
    ))
    return registry


def check_cross_authority_touch_rejected():
    registry = _fresh_registry()
    loop = HypothesisLoop(registry=registry, owned_tunable_names=frozenset({"safe_tunable"}))
    raised = False
    try:
        loop.apply_and_measure(
            "sensitive_tunable", 3.0, "shouldn't be allowed",
            measure_fn=lambda: 1.0, better_fn=LOWER_IS_BETTER,
        )
    except CrossAuthorityError:
        raised = True
    check("B13.4: touching a tunable outside owned_tunable_names raises CrossAuthorityError", raised)
    check("B13.4: a rejected touch never applies -- value untouched", registry.get("sensitive_tunable").value == 2.0)


def check_disjoint_authorities_never_collide():
    registry = _fresh_registry()
    runtime_loop = HypothesisLoop(registry=registry, owned_tunable_names=frozenset({"safe_tunable"}))
    reflection_loop = HypothesisLoop(registry=registry, owned_tunable_names=frozenset({"sensitive_tunable"}))

    values_iter = iter([100.0, 50.0])
    runtime_loop.apply_and_measure(
        "safe_tunable", 20.0, "runtime's own tunable",
        measure_fn=lambda: next(values_iter), better_fn=LOWER_IS_BETTER,
    )
    check("B13.4: runtime loop can touch its own tunable", registry.get("safe_tunable").value == 20.0)

    raised = False
    try:
        runtime_loop.apply_and_measure(
            "sensitive_tunable", 3.0, "not runtime's authority",
            measure_fn=lambda: 1.0, better_fn=LOWER_IS_BETTER,
        )
    except CrossAuthorityError:
        raised = True
    check("B13.4: runtime loop cannot reach into reflection_loop's own authority", raised)

    reflection_values = iter([100.0, 40.0])
    reflection_loop.apply_and_measure(
        "sensitive_tunable", 4.0, "reflection's own tunable, its own authority",
        measure_fn=lambda: next(reflection_values), better_fn=LOWER_IS_BETTER,
        equivalence_check_fn=lambda: True,
    )
    check("B13.4: reflection loop can freely touch its OWN tunable, symmetric proof", registry.get("sensitive_tunable").value == 4.0)


def check_safe_tunable_kept_on_improvement_no_gate():
    registry = _fresh_registry()
    loop = HypothesisLoop(registry=registry, owned_tunable_names=frozenset({"safe_tunable"}))
    values_iter = iter([100.0, 40.0])
    record = loop.apply_and_measure(
        "safe_tunable", 25.0, "raising it should lower measured load",
        measure_fn=lambda: next(values_iter), better_fn=LOWER_IS_BETTER,
    )
    check("SAFE tunable: kept on genuine improvement", record.decision == "kept")
    check("SAFE tunable: no gate applied at all (cannot change outcomes by construction)", record.gate_applied is False and record.gate_passed is None)
    check("SAFE tunable: registry reflects the new value", registry.get("safe_tunable").value == 25.0)


def check_safe_tunable_rolled_back_on_no_improvement():
    registry = _fresh_registry()
    loop = HypothesisLoop(registry=registry, owned_tunable_names=frozenset({"safe_tunable"}))
    values_iter = iter([100.0, 150.0])  # got worse
    record = loop.apply_and_measure(
        "safe_tunable", 25.0, "expected improvement that didn't happen",
        measure_fn=lambda: next(values_iter), better_fn=LOWER_IS_BETTER,
    )
    check("SAFE tunable: rolled back when measurement did not improve", record.decision == "rolled_back")
    check("SAFE tunable: registry value genuinely reverted, not left at the failed proposal", registry.get("safe_tunable").value == 10.0)


def check_sensitive_tunable_rejected_without_equivalence_check():
    registry = _fresh_registry()
    loop = HypothesisLoop(registry=registry, owned_tunable_names=frozenset({"sensitive_tunable"}))
    values_iter = iter([100.0, 40.0])  # genuinely improved
    record = loop.apply_and_measure(
        "sensitive_tunable", 4.0, "improved but no safety check supplied",
        measure_fn=lambda: next(values_iter), better_fn=LOWER_IS_BETTER,
        # equivalence_check_fn deliberately omitted
    )
    check(
        "B13.2: a SENSITIVE improvement with NO equivalence_check_fn is automatically rejected, not a free pass",
        record.decision == "rolled_back" and record.gate_applied is True and record.gate_passed is False,
    )
    check("B13.2: registry value reverted", registry.get("sensitive_tunable").value == 2.0)


def check_sensitive_tunable_rejected_on_failed_equivalence():
    registry = _fresh_registry()
    loop = HypothesisLoop(registry=registry, owned_tunable_names=frozenset({"sensitive_tunable"}))
    values_iter = iter([100.0, 40.0])  # genuinely improved
    record = loop.apply_and_measure(
        "sensitive_tunable", 4.0, "improved but changes real outcomes",
        measure_fn=lambda: next(values_iter), better_fn=LOWER_IS_BETTER,
        equivalence_check_fn=lambda: False,
    )
    check(
        "B13.2: a performance win that FAILS replay-hash equivalence is automatically rejected -- no judgment call",
        record.decision == "rolled_back" and record.gate_applied is True and record.gate_passed is False,
    )
    check("B13.2: registry value reverted despite the real measured improvement", registry.get("sensitive_tunable").value == 2.0)


def check_sensitive_tunable_kept_on_passed_equivalence():
    registry = _fresh_registry()
    loop = HypothesisLoop(registry=registry, owned_tunable_names=frozenset({"sensitive_tunable"}))
    values_iter = iter([100.0, 40.0])
    record = loop.apply_and_measure(
        "sensitive_tunable", 4.0, "improved and provably equivalent",
        measure_fn=lambda: next(values_iter), better_fn=LOWER_IS_BETTER,
        equivalence_check_fn=lambda: True,
    )
    check("B13.2: kept once BOTH improvement and equivalence pass", record.decision == "kept" and record.gate_applied and record.gate_passed)
    check("B13.2: registry reflects the new, gate-cleared value", registry.get("sensitive_tunable").value == 4.0)


def check_equivalence_check_only_called_when_improved():
    registry = _fresh_registry()
    loop = HypothesisLoop(registry=registry, owned_tunable_names=frozenset({"sensitive_tunable"}))
    calls = []

    def tracked_check():
        calls.append(1)
        return True

    values_iter = iter([100.0, 150.0])  # got WORSE
    loop.apply_and_measure(
        "sensitive_tunable", 4.0, "no point paying for a replay check on a losing change",
        measure_fn=lambda: next(values_iter), better_fn=LOWER_IS_BETTER,
        equivalence_check_fn=tracked_check,
    )
    check("efficiency: equivalence_check_fn is never called when the measurement itself didn't improve", len(calls) == 0)


def check_history_records_every_attempt_with_reason():
    registry = _fresh_registry()
    history = AdaptationHistory()
    loop = HypothesisLoop(registry=registry, owned_tunable_names=frozenset({"safe_tunable", "sensitive_tunable"}), history=history)

    values_iter = iter([100.0, 40.0, 100.0, 40.0])
    loop.apply_and_measure("safe_tunable", 25.0, "h1", measure_fn=lambda: next(values_iter), better_fn=LOWER_IS_BETTER)
    loop.apply_and_measure("sensitive_tunable", 4.0, "h2", measure_fn=lambda: next(values_iter), better_fn=LOWER_IS_BETTER, equivalence_check_fn=lambda: True)

    check("B13.3: history records exactly the attempts made", len(history.all()) == 2)
    check("B13.3: kept()/rolled_back() split correctly", len(history.kept()) == 2 and len(history.rolled_back()) == 0)
    check("B13.3: every record carries a real, non-empty reason", all(isinstance(r, AdaptationRecord) and r.reason for r in history.all()))


def check_history_is_bounded():
    history = AdaptationHistory()
    for i in range(ADAPTATION_HISTORY_MAX + 50):
        history.record(AdaptationRecord(
            hypothesis=f"h{i}", tunable_name="x", safety_class=SafetyClass.SAFE,
            before_value=0.0, after_value=1.0, measured_before=0.0, measured_after=0.0,
            gate_applied=False, gate_passed=None, decision="kept", reason="synthetic",
        ))
    check("B13.3: history stays bounded at ADAPTATION_HISTORY_MAX", len(history.all()) == ADAPTATION_HISTORY_MAX)
    check("B13.3: the OLDEST records are the ones dropped (newest survive)", history.all()[-1].hypothesis == f"h{ADAPTATION_HISTORY_MAX + 49}")


def main():
    check_cross_authority_touch_rejected()
    check_disjoint_authorities_never_collide()
    check_safe_tunable_kept_on_improvement_no_gate()
    check_safe_tunable_rolled_back_on_no_improvement()
    check_sensitive_tunable_rejected_without_equivalence_check()
    check_sensitive_tunable_rejected_on_failed_equivalence()
    check_sensitive_tunable_kept_on_passed_equivalence()
    check_equivalence_check_only_called_when_improved()
    check_history_records_every_attempt_with_reason()
    check_history_is_bounded()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED: {FAILURES}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
