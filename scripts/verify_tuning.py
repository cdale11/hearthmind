#!/usr/bin/env python3
"""Tier 5 B6 verification (adaptive tuning).

Standalone verification script, not a unittest — same convention as
every other verify_*.py in this directory. Exercises `hearthmind.
simulation.tuning` directly; nothing here is wired into any real
control point yet (see the module's own docstring).

Checks:
  1. Registering a tunable, reading it back, duplicate-name rejection.
  2. `adjust`/`set_value` clamp to the tunable's legal range in both
     directions, never overshooting.
  3. `BangBangController` pushes the tunable UP when measured is below
     target (for an `increases_measurement=True` tunable) and DOWN
     when above — the basic feedback direction.
  4. The same controller on an `increases_measurement=False` tunable
     (raising the tunable value LOWERS the measured signal) pushes in
     the opposite direction for the same measured/target relationship
     — proving the direction flag is actually load-bearing, not just
     plumbing that happens to work for one polarity.
  5. Hysteresis dead-zone: a measured value within `target +-
     hysteresis` produces NO change, even repeatedly — the mechanism
     that stops the controller chattering back and forth every reading.
  6. `register_llm_pacing_tunables` populates a real, correctly-typed
     tunable set (all SENSITIVE, since every one changes real LLM call
     timing/ordering) with no duplicate names.
"""
from __future__ import annotations

import sys

from hearthmind.simulation.tuning import (
    BangBangController,
    SafetyClass,
    Tunable,
    TunableRegistry,
    register_llm_pacing_tunables,
)


def check_register_get_duplicate() -> None:
    reg = TunableRegistry()
    reg.register(Tunable(name="a", value=5, min_value=0, max_value=10, step=1,
                          safety_class=SafetyClass.SAFE))
    assert reg.get("a").value == 5
    try:
        reg.register(Tunable(name="a", value=1, min_value=0, max_value=10, step=1,
                              safety_class=SafetyClass.SAFE))
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on duplicate name")


def check_clamping() -> None:
    reg = TunableRegistry()
    reg.register(Tunable(name="a", value=5, min_value=0, max_value=10, step=3,
                          safety_class=SafetyClass.SAFE))
    for _ in range(10):
        reg.adjust("a", 3)
    assert reg.get("a").value == 10, reg.get("a").value
    for _ in range(10):
        reg.adjust("a", -3)
    assert reg.get("a").value == 0, reg.get("a").value
    assert reg.set_value("a", 999) == 10
    assert reg.set_value("a", -999) == 0


def check_bang_bang_basic_direction() -> None:
    reg = TunableRegistry()
    reg.register(Tunable(name="concurrency", value=2, min_value=1, max_value=8, step=1,
                          safety_class=SafetyClass.SENSITIVE))
    ctrl = BangBangController(tunable_name="concurrency", target=50.0, hysteresis=5.0,
                               increases_measurement=True)
    # Measured (10) well below target (50) -> push tunable UP.
    new_value = ctrl.step(reg, measured=10.0)
    assert new_value == 3, new_value
    # Measured (90) well above target -> push tunable DOWN.
    new_value = ctrl.step(reg, measured=90.0)
    assert new_value == 2, new_value


def check_bang_bang_inverted_direction() -> None:
    reg = TunableRegistry()
    reg.register(Tunable(name="slowdown_ratio", value=0.5, min_value=0.1, max_value=1.0,
                          step=0.05, safety_class=SafetyClass.SENSITIVE))
    # Raising this tunable LOWERS the measured pressure (it triggers
    # slowdown pacing sooner) -- increases_measurement=False.
    ctrl = BangBangController(tunable_name="slowdown_ratio", target=1.0, hysteresis=0.05,
                               increases_measurement=False)
    # Measured pressure (2.0) well ABOVE target -> want it to fall ->
    # raise the tunable (since raising it lowers measurement).
    new_value = ctrl.step(reg, measured=2.0)
    assert abs(new_value - 0.55) < 1e-9, new_value
    # Measured pressure (0.1) well BELOW target -> want it to rise ->
    # lower the tunable.
    new_value = ctrl.step(reg, measured=0.1)
    assert abs(new_value - 0.5) < 1e-9, new_value


def check_hysteresis_dead_zone() -> None:
    reg = TunableRegistry()
    reg.register(Tunable(name="a", value=5, min_value=0, max_value=10, step=1,
                          safety_class=SafetyClass.SAFE))
    ctrl = BangBangController(tunable_name="a", target=50.0, hysteresis=10.0,
                               increases_measurement=True)
    for measured in (42.0, 45.0, 50.0, 55.0, 59.0):
        result = ctrl.step(reg, measured=measured)
        assert result == 5, (measured, result)


def check_llm_pacing_tunables_registered() -> None:
    reg = TunableRegistry()
    register_llm_pacing_tunables(reg)
    all_tunables = reg.all()
    assert len(all_tunables) == 4, len(all_tunables)
    assert "llm_max_concurrent" in all_tunables
    assert "llm_pressure_slowdown_start_ratio" in all_tunables
    for name, t in all_tunables.items():
        assert t.safety_class is SafetyClass.SENSITIVE, (name, t.safety_class)
        assert t.description, f"{name} missing a description"


def main() -> int:
    checks = [
        check_register_get_duplicate,
        check_clamping,
        check_bang_bang_basic_direction,
        check_bang_bang_inverted_direction,
        check_hysteresis_dead_zone,
        check_llm_pacing_tunables_registered,
    ]
    for check in checks:
        check()
        print(f"OK: {check.__name__}")
    print(f"Tuning verification OK — {len(checks)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
