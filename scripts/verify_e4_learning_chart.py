#!/usr/bin/env python3
"""Tier 7 HCA Stage E, E4 (docs/ROADMAP-2026-07-REMAINING.md, Phase 7,
explicit user instruction "Start E4"): the "learning chart" — HCA's
own headline falsification test (§8): "deliberative cost per unit of
emergence must FALL as a world matures... if LLM calls fall but
emergence falls proportionally, impasse-gating is just starvation with
extra steps."

Verifies `hearthmind.cognition.observatory.compute_deliberation_sample`
directly (the real per-1000-tick rate + §8 cost-ratio math), then end
to end through a real `SimulationEngine._maybe_sample_deliberation_
emergence` — the exact real production method the tick loop dispatches
to daily — driving the real clock and the real `CognitionRunner.
calls_succeeded`/`World.next_emergence_id` counters directly (same
"advance the clock and the real counter, call the real registered
method" technique `verify_ml_g2_workload_forecaster.py` already
established for its own sibling daily sampler)."""
from __future__ import annotations

import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def ticks_per_day(eng) -> int:
    return eng.world.config.minutes_per_day // eng.world.config.sim_minutes_per_tick


def main() -> int:
    from hearthmind.cognition.observatory import compute_deliberation_sample

    # --- direct math, hand-computed ---
    sample = compute_deliberation_sample(
        tick=1000, prev_tick=0, calls_succeeded=50, prev_calls_succeeded=0,
        emergence_total=10, prev_emergence_total=0,
    )
    check("compute_deliberation_sample: elapsed_ticks is the real tick delta",
          sample["elapsed_ticks"] == 1000)
    check("compute_deliberation_sample: deliberative_calls is the real calls delta",
          sample["deliberative_calls"] == 50)
    check("compute_deliberation_sample: deliberative_calls_per_1000_ticks matches hand math (50/1000*1000=50.0)",
          sample["deliberative_calls_per_1000_ticks"] == 50.0)
    check("compute_deliberation_sample: emergence_per_1000_ticks matches hand math (10/1000*1000=10.0)",
          sample["emergence_per_1000_ticks"] == 10.0)
    check("compute_deliberation_sample: cost_per_emergence matches hand math (50/10=5.0)",
          sample["cost_per_emergence"] == 5.0)

    # --- a degenerate (non-positive elapsed) window returns None, not
    #     a divide-by-zero or a fabricated rate ---
    check("compute_deliberation_sample returns None for a same-tick window",
          compute_deliberation_sample(100, 100, 5, 0, 1, 0) is None)
    check("compute_deliberation_sample returns None for an out-of-order (negative elapsed) window",
          compute_deliberation_sample(50, 100, 5, 0, 1, 0) is None)

    # --- zero real emergence this window: cost_per_emergence is
    #     honestly None (undefined), never a free 0.0 ---
    zero_emergence = compute_deliberation_sample(1000, 0, 20, 0, 0, 0)
    check("cost_per_emergence is None (undefined), not 0.0, when emergence_count is zero",
          zero_emergence["cost_per_emergence"] is None and zero_emergence["emergence_count"] == 0)

    # --- a stale/reordered counter never produces a negative delta ---
    stale = compute_deliberation_sample(1000, 0, 5, 20, 3, 10)
    check("a counter that appears to have decreased clamps its delta to 0, never negative",
          stale["deliberative_calls"] == 0 and stale["emergence_count"] == 0)

    # --- end to end: a real SimulationEngine, the real production
    #     method, the real _TICK_JOBS registration ---
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.simulation.engine import SimulationEngine

    d = tempfile.mkdtemp()
    conn = connect(f"{d}/e4.db")
    cfg = Config(db_path=f"{d}/e4.db", llm_enabled=False, seed=13, initial_population=4, width=16, height=16)
    eng = SimulationEngine.load_or_create(conn, cfg)

    check("_maybe_sample_deliberation_emergence is registered in the real _TICK_JOBS table",
          any(name == "_maybe_sample_deliberation_emergence" for name, _ in SimulationEngine._TICK_JOBS))

    # A non-day_end tick is a genuine no-op.
    before_history = len(eng._deliberation_emergence_history)
    before_prev = eng._deliberation_sample_prev
    eng._maybe_sample_deliberation_emergence([])
    check("a non-day_end call is a genuine no-op (history and baseline both untouched)",
          len(eng._deliberation_emergence_history) == before_history
          and eng._deliberation_sample_prev == before_prev)

    # The very first real day_end call: elapsed since the (0,0,0)
    # origin baseline may be 0 at a fresh world's tick 0 -- no sample
    # yet, but the real baseline still advances so the NEXT call
    # measures a real window.
    eng._maybe_sample_deliberation_emergence(["day_end"])
    check("the first real day_end call at tick 0 produces no sample yet (zero-elapsed baseline)",
          len(eng._deliberation_emergence_history) == 0)
    check("the first real day_end call still records a real baseline to diff the next sample against",
          eng._deliberation_sample_prev[0] == eng.world.clock.tick_count)

    # Advance a real day, bump the real production counters directly
    # (the same counters a real LLM call succeeding / a real surprise-
    # gated emergence entry would bump), call the real method again.
    eng.world.clock.tick_count += ticks_per_day(eng)
    eng._cognition_runner.calls_succeeded += 8
    eng.world.next_emergence_id += 3
    eng._maybe_sample_deliberation_emergence(["day_end"])
    check("a real elapsed day with real counter deltas produces exactly one real sample",
          len(eng._deliberation_emergence_history) == 1)
    real_sample = eng._deliberation_emergence_history[-1]
    check("the real sample's deliberative_calls matches the real calls_succeeded delta",
          real_sample["deliberative_calls"] == 8)
    check("the real sample's emergence_count matches the real next_emergence_id delta",
          real_sample["emergence_count"] == 3)
    check("the real sample's tick matches the real clock's current tick",
          real_sample["tick"] == eng.world.clock.tick_count)

    # A second real day, this time with genuinely ZERO new emergence --
    # cost_per_emergence must honestly read None, not a fabricated 0.
    eng.world.clock.tick_count += ticks_per_day(eng)
    eng._cognition_runner.calls_succeeded += 4
    eng._maybe_sample_deliberation_emergence(["day_end"])
    check("two real day_end calls produce exactly two real samples",
          len(eng._deliberation_emergence_history) == 2)
    zero_window = eng._deliberation_emergence_history[-1]
    check("a real window with genuinely zero new emergence reports cost_per_emergence honestly as None",
          zero_window["emergence_count"] == 0 and zero_window["cost_per_emergence"] is None)

    # --- full_diagnostics() surfaces the real history verbatim ---
    report = eng.full_diagnostics()
    check("full_diagnostics()['deliberation_emergence_history'] reflects the real history",
          report["deliberation_emergence_history"] == list(eng._deliberation_emergence_history))

    # --- bounded: the deque never grows past its configured cap ---
    from hearthmind.simulation.engine import DELIBERATION_EMERGENCE_HISTORY_MAX

    check("_deliberation_emergence_history is a genuinely bounded deque",
          eng._deliberation_emergence_history.maxlen == DELIBERATION_EMERGENCE_HISTORY_MAX)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
