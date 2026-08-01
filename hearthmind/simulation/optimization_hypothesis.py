"""B13 -- Optimization hypotheses (docs/HEARTHBENCH-RUNTIME-2026-07-23.md,
Part B, Hard Rule 14). Standalone infrastructure, same "never big-bang"
discipline as every other Tier 5 Runtime module -- not wired into
`simulation/engine.py`'s real pacing/scheduling constants yet.

Reuses B6's `Tunable`/`TunableRegistry`/`SafetyClass`
(`simulation/tuning.py`) directly rather than a second tunable model --
this module is the LOOP that proposes/applies/measures/keeps-or-rolls-
back a change to an EXISTING tunable, not a parallel value store.
`SafetyClass.SENSITIVE`'s own docstring already named this exact gap
("would need B13.2's replay-hash equivalence gate... B13 itself is
unbuilt") -- this module is that gate, finally built.

B13.1 `HypothesisLoop.apply_and_measure`: observe (measure_fn, called
     before) -> hypothesize (the caller's own hypothesis text) -> apply
     (behind the registry's normal clamp, not a special path) -> measure
     (measure_fn, called after) -> keep or roll back, every step recorded
     as a real `AdaptationRecord` (B13.3) -- nothing here is silently
     decided and forgotten.
B13.2 The semantic-safety gate: a `SafetyClass.SENSITIVE` tunable change
     may ONLY be kept if a caller-supplied `equivalence_check_fn` (real
     production wiring: B15.1's `verify_replay_hash.py` machinery run on
     a forked world) reports True -- no `equivalence_check_fn` at all is
     treated as a FAILED gate, never a free pass. `SAFE` tunables skip
     the gate entirely (cannot change simulation outcomes by
     construction, per B6.1's own `SafetyClass` docstring). "A
     performance win that changes outcomes is automatically rejected --
     no judgment call" is enforced in code here, not left as a
     convention for a future caller to remember.
B13.3 `AdaptationHistory`: a bounded, browsable, append-only record of
     every attempt -- hypothesis text, tunable, before/after value,
     measured before/after, whether the safety gate applied and its
     verdict, and the final kept/rolled-back decision with a real
     reason string.
B13.4 The Runtime/Reflection separation, as code: a `HypothesisLoop` is
     constructed with a fixed `owned_tunable_names` set; any attempt to
     touch a tunable outside that set raises `CrossAuthorityError`
     immediately, before anything is measured or applied -- two loops
     built over disjoint name sets (one standing in for this Runtime's
     own tunables, one for Reflection's) can never collide, verified
     directly.
B13.5 (an optional evolutionary search over multi-dimensional tunable
     sets) is explicitly NOT built this pass -- the item's own text
     gates it behind "B13.1-B13.2 solid" first, and it is real, distinct
     future work (evolving several tunables jointly under this same
     safety-gate constraint, not the same thing as L6's model-genome
     evolution or B6.2's single-tunable bang-bang control).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from hearthmind.simulation.tuning import SafetyClass, TunableRegistry


class CrossAuthorityError(Exception):
    """B13.4: raised when a `HypothesisLoop` is asked to touch a
    tunable outside its own declared authority."""


ADAPTATION_HISTORY_MAX = 500


@dataclass
class AdaptationRecord:
    """B13.3. One full attempt, kept or rolled back, with the WHY."""

    hypothesis: str
    tunable_name: str
    safety_class: SafetyClass
    before_value: float
    after_value: float
    measured_before: float
    measured_after: float
    gate_applied: bool
    gate_passed: Optional[bool]
    decision: str  # "kept" | "rolled_back"
    reason: str


@dataclass
class AdaptationHistory:
    """B13.3's bounded, browsable record. A plain list, capped -- same
    "bounded, never unbounded growth" discipline as every other
    persisted-history structure in this codebase."""

    records: list = field(default_factory=list)

    def record(self, entry: AdaptationRecord) -> None:
        self.records.append(entry)
        if len(self.records) > ADAPTATION_HISTORY_MAX:
            self.records = self.records[-ADAPTATION_HISTORY_MAX:]

    def all(self) -> list:
        return list(self.records)

    def kept(self) -> list:
        return [r for r in self.records if r.decision == "kept"]

    def rolled_back(self) -> list:
        return [r for r in self.records if r.decision == "rolled_back"]


@dataclass
class HypothesisLoop:
    """B13.1/B13.2/B13.4. `owned_tunable_names` is this loop's whole
    declared authority -- the mechanical form of B13.4's invariant.
    `history` defaults to a fresh `AdaptationHistory` but is normally
    shared across every loop in a process so B13.3's record stays one
    real browsable list, not one per authority."""

    registry: TunableRegistry
    owned_tunable_names: frozenset
    history: AdaptationHistory = field(default_factory=AdaptationHistory)

    def _require_ownership(self, tunable_name: str) -> None:
        if tunable_name not in self.owned_tunable_names:
            raise CrossAuthorityError(
                f"{tunable_name!r} is not owned by this HypothesisLoop "
                f"(owns: {sorted(self.owned_tunable_names)}) -- B13.4's "
                f"Runtime/Reflection separation forbids touching a "
                f"tunable outside one's own declared authority."
            )

    def apply_and_measure(
        self,
        tunable_name: str,
        proposed_value: float,
        hypothesis: str,
        measure_fn: Callable[[], float],
        better_fn: Callable[[float, float], bool],
        equivalence_check_fn: Optional[Callable[[], bool]] = None,
    ) -> AdaptationRecord:
        """The full B13.1 loop for one tunable. `better_fn(before,
        after)` says whether the measured value genuinely improved --
        direction is caller-supplied since different metrics improve
        in opposite directions (lower latency is better, higher
        throughput is better), same discipline `BangBangController`
        already uses for `increases_measurement`. `equivalence_check_
        fn`, when given, is called ONLY for a SENSITIVE tunable, and
        ONLY after a genuine measured improvement (no reason to pay a
        real replay-hash check for a change that wouldn't be kept
        anyway)."""
        self._require_ownership(tunable_name)

        t = self.registry.get(tunable_name)
        before_value = t.value
        measured_before = measure_fn()

        self.registry.set_value(tunable_name, proposed_value)
        after_value = t.value
        measured_after = measure_fn()

        improved = better_fn(measured_before, measured_after)

        gate_applied = False
        gate_passed: Optional[bool] = None
        if improved and t.safety_class is SafetyClass.SENSITIVE:
            gate_applied = True
            gate_passed = bool(equivalence_check_fn()) if equivalence_check_fn is not None else False

        if not improved:
            decision, reason = "rolled_back", "measurement did not improve"
        elif gate_applied and not gate_passed:
            decision, reason = "rolled_back", "sensitive tunable failed (or skipped) the semantic-safety equivalence gate"
        else:
            decision, reason = "kept", "measurement improved" + (" and passed the semantic-safety gate" if gate_applied else "")

        if decision == "rolled_back":
            self.registry.set_value(tunable_name, before_value)

        record = AdaptationRecord(
            hypothesis=hypothesis,
            tunable_name=tunable_name,
            safety_class=t.safety_class,
            before_value=before_value,
            after_value=after_value,
            measured_before=measured_before,
            measured_after=measured_after,
            gate_applied=gate_applied,
            gate_passed=gate_passed,
            decision=decision,
            reason=reason,
        )
        self.history.record(record)
        return record
