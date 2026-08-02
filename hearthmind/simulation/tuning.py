"""Tier 5 B6 — Adaptive tuning.

docs/HEARTHBENCH-RUNTIME-2026-07-23.md, Part B [Hard Rule 6]:
"Deterministic, no LLM — per the doc's closing note (evolutionary
algorithms, statistics, optimization, feedback control)." This module
is classical control only, by the item's own explicit instruction —
consistent with the broader ML-candidate audit run alongside this
pass (see CLAUDE.md's v1.34.168 entry for the full writeup): nothing
in this runtime currently has the labeled training signal or call
volume to justify a trained model over a measured feedback loop, so a
bang-bang controller is the right tool here, not a placeholder for one.

**`llm_max_concurrent` is now wired to a real control point** (this
module's own long-flagged "real future migration," done): `Simulation
Engine._maybe_tune_llm_concurrency` (engine.py) runs a real `BangBang
Controller` against this registry's `llm_max_concurrent` `Tunable`
once a day, driven by `CognitionRunner.stats()`'s own already-tracked
rolling p95 latency — the exact real signal CLAUDE.md's own long
documented manual-retune history (4 -> 2 -> 1 -> 2 -> 1 -> 2) was
always driven by. A real change calls `CognitionRunner.resize_
concurrency()` (llm/jobs.py's `_ResizableSemaphore`), which live-
resizes the actual concurrency gate in-flight LLM calls run through —
this is a genuine behavior change to a live process, not metadata.

Scoped deliberately narrow, matching this constant's own precedent
for why it's safe to automate without B13's full sandboxed replay-
hash equivalence gate: `llm_max_concurrent` only changes LLM call
*timing/scheduling*, never deterministic `World` state (Determinism/
reproducibility is explicitly NOT a project requirement for LLM-
related paths, per CLAUDE.md's own workflow rules) — every past
manual retune of this exact constant was likewise never gated behind
a replay-hash check. Anti-chatter discipline: `BangBangController`'s
own hysteresis dead-zone, a once-a-day cadence, a minimum-evidence
floor (skip while the latency window is too sparse to trust), and a
bounded ±1 step per check (the `Tunable`'s own `step`/`min_value`/
`max_value`) together bound how much and how often this can move.
Every real change is logged to `SimulationEngine._adaptive_tuning_
log` (bounded, dev-console-visible via `full_diagnostics()`) so a
live deployment can see WHY its concurrency changed, not just that
it did.

The other three registered tunables (`llm_pressure_slowdown_start_
ratio`/`llm_pressure_speedup_start_ratio`/`llm_pressure_min_speedup_
multiplier`) remain metadata-only, same as before — real future work,
not attempted this pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SafetyClass(Enum):
    """B6.1's semantic-safety class: `SAFE` tunables cannot change
    simulation outcomes by construction (e.g. a diagnostics sample
    rate); `SENSITIVE` ones can (e.g. LLM concurrency, which changes
    real call timing/ordering) and would need B13.2's replay-hash
    equivalence gate before an automated change to one is trusted —
    B13 itself is unbuilt, so today every `SENSITIVE` tunable's
    automated adjustments are informational only until B13 exists to
    actually gate them."""

    SAFE = "safe"
    SENSITIVE = "sensitive"


@dataclass
class Tunable:
    """B6.1's descriptor: a legal range, a step size, and a safety
    class, alongside the live value itself."""

    name: str
    value: float
    min_value: float
    max_value: float
    step: float
    safety_class: SafetyClass
    description: str = ""

    def clamp(self, v: float) -> float:
        return max(self.min_value, min(self.max_value, v))


class TunableRegistry:
    """B6.1's registry — the general framework B6.3 asks the existing
    LLM pacing controller to be re-expressed under, rather than staying
    a special case."""

    def __init__(self) -> None:
        self._tunables: dict[str, Tunable] = {}

    def register(self, tunable: Tunable) -> None:
        if tunable.name in self._tunables:
            raise ValueError(f"duplicate tunable name: {tunable.name!r}")
        self._tunables[tunable.name] = tunable

    def get(self, name: str) -> Tunable:
        return self._tunables[name]

    def all(self) -> dict[str, Tunable]:
        return dict(self._tunables)

    def adjust(self, name: str, delta: float) -> float:
        """Moves a tunable by `delta`, clamped to its legal range.
        Returns the resulting value."""
        t = self._tunables[name]
        t.value = t.clamp(t.value + delta)
        return t.value

    def set_value(self, name: str, value: float) -> float:
        t = self._tunables[name]
        t.value = t.clamp(value)
        return t.value


@dataclass
class BangBangController:
    """B6.2's simplest controller shape: push a tunable one step toward
    a target, with a hysteresis dead-zone so it doesn't chatter back
    and forth every reading. `increases_measurement` records whether
    RAISING the tunable's value raises or lowers the thing being
    measured — needed because different tunables push the measured
    signal in opposite directions (e.g. raising `llm_max_concurrent`
    plausibly raises measured latency/backlog; raising a slowdown
    multiplier plausibly lowers it), and the controller must move the
    tunable the correct direction regardless of which kind it is.
    """

    tunable_name: str
    target: float
    hysteresis: float
    increases_measurement: bool = True

    def step(self, registry: TunableRegistry, measured: float) -> float:
        t = registry.get(self.tunable_name)
        error = measured - self.target
        if abs(error) <= self.hysteresis:
            return t.value  # inside the dead zone -- no-op, avoids chattering
        want_measurement_to_rise = error < 0  # measured below target -> push it up
        move_tunable_up = want_measurement_to_rise == self.increases_measurement
        delta = t.step if move_tunable_up else -t.step
        return registry.adjust(self.tunable_name, delta)


def register_llm_pacing_tunables(registry: TunableRegistry) -> None:
    """B6.3: registers the real existing LLM-pacing constants
    (CLAUDE.md's documented `Config`/`engine.py` values, current as of
    this pass) as a real tunable set under the general B6 framework —
    metadata only, see the module docstring for why this doesn't
    rewire the live pacing code itself."""
    registry.register(Tunable(
        name="llm_max_concurrent", value=2, min_value=1, max_value=8, step=1,
        safety_class=SafetyClass.SENSITIVE,
        description="Config.llm_max_concurrent -- real Ollama/llama-server call concurrency.",
    ))
    registry.register(Tunable(
        name="llm_pressure_slowdown_start_ratio", value=0.5,
        min_value=0.1, max_value=1.0, step=0.05,
        safety_class=SafetyClass.SENSITIVE,
        description="engine.py LLM_PRESSURE_SLOWDOWN_START_RATIO -- backlog/limit ratio where tick pacing begins to slow.",
    ))
    registry.register(Tunable(
        name="llm_pressure_speedup_start_ratio", value=0.15,
        min_value=0.0, max_value=0.9, step=0.05,
        safety_class=SafetyClass.SENSITIVE,
        description="engine.py LLM_PRESSURE_SPEEDUP_START_RATIO -- backlog/limit ratio below which ticks speed up.",
    ))
    registry.register(Tunable(
        name="llm_pressure_min_speedup_multiplier", value=0.4,
        min_value=0.1, max_value=1.0, step=0.05,
        safety_class=SafetyClass.SENSITIVE,
        description="engine.py LLM_PRESSURE_MIN_SPEEDUP_MULTIPLIER -- fastest tick-gap multiplier once genuinely idle.",
    ))
