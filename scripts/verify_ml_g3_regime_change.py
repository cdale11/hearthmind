#!/usr/bin/env python3
"""Tier 7 HCA Stage G, G3 (explicit user instruction: "Continue G3"):
"forget obsolete assumptions," made testable.

G3's own stated test (docs/ROADMAP-2026-07-REMAINING.md /
docs/COGNITIVE-ARCHITECTURE-2026-08-02.md): "a specialist trained
against a pattern that then genuinely stops holding should measurably
re-adapt within a bounded, stated-in-advance number of `learn()`
cycles... a synthetic regime-change scenario -- pre-shift error low,
post-shift error spikes then falls back down within N cycles."

Investigated before writing any new "forgetting" mechanism: does the
already-shipped `LearningSpecialist.learn()` loop (G1, `continual_
train_mlp` + `ReplayBuffer` + the shadow gate) already have this
property, or does replay rehearsal of stale examples actively resist
adaptation? A direct synthetic run (below) confirms it already re-
adapts -- the shadow gate always compares a candidate against a
holdout drawn from the world AS IT IS NOW, never the stale regime, so
a candidate genuinely closer to the new pattern keeps winning gate
comparisons regardless of what's mixed into replay. No new forgetting
mechanism was invented for a problem that doesn't reproduce; this
script is the real, stated-in-advance N=15 bound that finding rests
on, plus a check that G3's real added observability (`LearningSpecialist.
error_history`) faithfully records the whole regime-change trace.

No unittest, same standalone-script convention as every sibling
`verify_*.py`.
"""
from __future__ import annotations

import random
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.ml.primitives import MLP
from hearthmind.ml.specialist import ERROR_HISTORY_MAX, LearningSpecialist
from hearthmind.ml.training import TrainingExample, mean_loss

FAILURES: list[str] = []

# The stated-in-advance bound this script exists to prove: real
# post-shift recovery must land within this many real learn() cycles.
REGIME_SHIFT_RECOVERY_CYCLES = 15
# "Recovered" means holdout loss on the NEW regime falls back within
# this multiple of the pre-shift steady-state floor -- a real,
# concrete, checkable definition of "falls back down," not a vibe.
REGIME_SHIFT_RECOVERY_TOLERANCE = 3.0


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def regime_examples(rng: random.Random, n: int, regime: str) -> list[TrainingExample]:
    """Two genuinely different linear signals sharing the same input
    range -- regime B is not a small perturbation of A, it's a
    different function entirely (opposite-signed coefficients), the
    real "the pattern stopped holding" case G3 names."""
    examples = []
    for _ in range(n):
        x0, x1 = rng.uniform(-1, 1), rng.uniform(-1, 1)
        noise = rng.uniform(-0.02, 0.02)
        if regime == "A":
            y = max(0.0, min(1.0, 0.5 * x0 - 0.3 * x1 + 0.5 + noise))
        else:
            y = max(0.0, min(1.0, -0.5 * x0 + 0.4 * x1 + 0.2 + noise))
        examples.append(TrainingExample(x=[x0, x1], y=[y]))
    return examples


def main() -> int:
    rng = random.Random(20260804)
    holdout_a = regime_examples(random.Random(9001), 200, "A")
    holdout_b = regime_examples(random.Random(9002), 200, "B")

    model = MLP.random_init([2, 6, 1], output_activation="sigmoid", seed=1)
    specialist = LearningSpecialist(model, replay_capacity=300, checkpoint_capacity=10)

    # --- pre-shift: establish a real, real low steady-state on regime A
    pre_shift_losses = []
    for cycle in range(6):
        examples = regime_examples(rng, 40, "A")
        specialist.learn(examples, holdout_a, tick=cycle, epochs=30, learning_rate=0.03, seed=cycle)
        pre_shift_losses.append(mean_loss(specialist.model, holdout_a))
    pre_shift_floor = min(pre_shift_losses)
    check(
        f"pre-shift error is genuinely low and converging (final={pre_shift_losses[-1]:.4f}, floor={pre_shift_floor:.4f})",
        pre_shift_losses[-1] < 0.05,
    )

    # --- the regime shift: the world's real pattern changes to B -----
    post_shift_losses = []
    recovered_at = None
    for cycle in range(6, 6 + REGIME_SHIFT_RECOVERY_CYCLES):
        examples = regime_examples(rng, 40, "B")
        specialist.learn(examples, holdout_b, tick=cycle, epochs=30, learning_rate=0.03, seed=cycle)
        loss = mean_loss(specialist.model, holdout_b)
        post_shift_losses.append(loss)
        if recovered_at is None and loss <= pre_shift_floor * REGIME_SHIFT_RECOVERY_TOLERANCE:
            recovered_at = cycle - 6 + 1  # 1-indexed cycle count since the shift

    check(
        f"post-shift error genuinely SPIKES on the very first post-shift cycle (spike={post_shift_losses[0]:.4f} vs pre-shift floor={pre_shift_floor:.4f})",
        post_shift_losses[0] > pre_shift_floor * REGIME_SHIFT_RECOVERY_TOLERANCE,
    )
    check(
        f"post-shift error FALLS BACK DOWN within the stated-in-advance bound "
        f"(recovered at real cycle {recovered_at} of a stated N={REGIME_SHIFT_RECOVERY_CYCLES})",
        recovered_at is not None and recovered_at <= REGIME_SHIFT_RECOVERY_CYCLES,
    )
    check(
        "the final post-shift reading is genuinely close to the pre-shift floor (real re-adaptation, not a fluke dip)",
        post_shift_losses[-1] <= pre_shift_floor * REGIME_SHIFT_RECOVERY_TOLERANCE,
    )

    # --- G3's own real observability addition: error_history faithfully
    #     records the whole trace, including the real spike-then-recovery
    #     shape, for a future Observatory panel (E5) to plot directly ---
    history = list(specialist.error_history)
    check(
        f"error_history recorded exactly one entry per real learn() call ({len(history)} entries for 6+{REGIME_SHIFT_RECOVERY_CYCLES} cycles)",
        len(history) == 6 + REGIME_SHIFT_RECOVERY_CYCLES,
    )
    check(
        "error_history's own recorded candidate_metric values reproduce the real spike at the shift boundary",
        history[6]["candidate_metric"] > history[5]["candidate_metric"],
    )
    check(
        "every error_history entry carries real, checkable fields (tick/baseline/candidate/accepted)",
        all({"tick", "baseline_metric", "candidate_metric", "accepted"} <= set(entry) for entry in history),
    )

    # --- error_history stays genuinely bounded over many more cycles --
    long_model = MLP.random_init([2, 4, 1], output_activation="sigmoid", seed=2)
    long_specialist = LearningSpecialist(long_model, replay_capacity=50, checkpoint_capacity=5)
    long_holdout = regime_examples(random.Random(1), 40, "A")
    for cycle in range(ERROR_HISTORY_MAX + 50):
        long_specialist.learn(regime_examples(rng, 10, "A"), long_holdout, tick=cycle, epochs=5, learning_rate=0.02, seed=cycle)
    check(
        f"error_history never exceeds its bound over {ERROR_HISTORY_MAX + 50} real cycles (len={len(long_specialist.error_history)})",
        len(long_specialist.error_history) == ERROR_HISTORY_MAX,
    )

    print(f"\n{len(FAILURES)} failure(s) out of a real check run.")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
